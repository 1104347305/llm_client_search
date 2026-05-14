"""
字段注册表 - 基于 Elasticsearch 的字段意图检索

功能：
1. 加载 config/field_definitions.yaml 中的意图定义
2. 写入 ES 索引（首次启动或强制重建时）
3. 根据自然语言查询检索相关字段意图（BM25 全文检索）
4. 格式化检索结果为 LLM prompt 片段

ES 索引设计：
- 一个文档 = 一个 intent
- retrieval_text 使用中文分词（ik_max_word / smartcn / standard）
- 原始 intent 完整存储在 _source 中
"""
import hashlib
import json
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml
from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk
from loguru import logger

from src.main.python.config.settings import settings
from src.main.python.models.field_mapping import get_field_context_group


# ES 索引 Mapping
def _build_index_mapping(analyzer: str, fingerprint: str) -> Dict[str, Any]:
    """
    构建 ES 索引 Mapping，支持多种中文分词器。
    analyzer 参数决定 index/search 使用的分词器名称：
      ik_max_word → index=ik_max_word, search=ik_smart
      smartcn     → index=smartcn,     search=smartcn
      standard    → index=standard,    search=standard（兜底）
    注意：boost 在 ES 8.x mapping 中已移除，改在查询时指定。
    """
    if analyzer == "ik_max_word":
        index_analyzer  = "ik_max_word"
        search_analyzer = "ik_smart"
    elif analyzer == "smartcn":
        index_analyzer  = "smartcn"
        search_analyzer = "smartcn"
    else:
        index_analyzer  = "standard"
        search_analyzer = "standard"

    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
        "mappings": {
            "_meta": {
                "intent_fingerprint": fingerprint,
            },
            "properties": {
                "id":             {"type": "keyword"},
                "field":          {"type": "keyword"},
                "operator":       {"type": "keyword"},
                "value_type":     {"type": "keyword"},
                "retrieval_text": {
                    "type": "text",
                    "analyzer": index_analyzer,
                    "search_analyzer": search_analyzer,
                },
                "description": {
                    "type": "text",
                    "analyzer": index_analyzer,
                    "search_analyzer": search_analyzer,
                },
                "notes": {
                    "type": "text",
                    "analyzer": index_analyzer,
                    "search_analyzer": search_analyzer,
                },
                "examples_text": {
                    "type": "text",
                    "analyzer": index_analyzer,
                    "search_analyzer": search_analyzer,
                },
                "negative_examples_text": {
                    "type": "text",
                    "analyzer": index_analyzer,
                    "search_analyzer": search_analyzer,
                },
                "enum":     {"type": "keyword"},
                "unit":     {"type": "keyword"},
                "format":   {"type": "keyword"},
                "examples": {"type": "object", "enabled": False},
                "negative_examples": {"type": "object", "enabled": False},
            }
        }
    }


class _TrieNode:
    """Trie 节点"""
    __slots__ = ("children", "intents")

    def __init__(self):
        self.children: Dict[str, "_TrieNode"] = {}
        self.intents: List[Dict] = []   # 以该节点结尾的枚举值对应的意图列表


class FieldRegistry:
    """字段意图注册表，基于 Elasticsearch 全文检索 + Trie 枚举精确匹配"""

    def __init__(
        self,
        yaml_path: Optional[str] = None,
        force_reindex: bool = False,
    ):
        if yaml_path is None:
            current_dir = Path(__file__).resolve().parent.parent.parent
            yaml_path = current_dir / f"{settings.FIELD_DEFINITIONS_PATH}"

        self.yaml_path = yaml_path
        self.index = settings.ES_FIELD_INDEX
        self.es_available = True

        # 构建 ES 客户端
        es_kwargs: Dict[str, Any] = {"hosts": [settings.ES_HOST]}
        if settings.ES_USERNAME and settings.ES_PASSWORD:
            es_kwargs["basic_auth"] = (settings.ES_USERNAME, settings.ES_PASSWORD)
        self.es = Elasticsearch(**es_kwargs)

        # 加载意图数据
        self.intents: List[Dict[str, Any]] = self._load_yaml()
        self._intents_by_id: Dict[str, Dict[str, Any]] = {
            str(intent.get("id", "")).strip(): intent
            for intent in self.intents
            if str(intent.get("id", "")).strip()
        }
        self._intents_fingerprint = self._compute_intents_fingerprint(self.intents)
        logger.info(f"Loaded {len(self.intents)} intents from {yaml_path}")

        # 字段 -> 枚举定义 / 口语别名映射，用于 L4 结果标准化
        self._field_to_enum_ref: Dict[str, str] = {}
        self._enum_values_by_field: Dict[str, List[str]] = {}
        self._value_mappings: Dict[str, Dict[str, str]] = {}
        self._query_normalize_pattern = None
        self._query_normalize_lookup: Dict[str, str] = {}
        self._build_enum_metadata()
        self._load_value_mappings()
        self._build_query_normalizer()

        # 构建枚举值 Trie 树（用于快速枚举命中检索）
        self._enum_trie = self._build_enum_trie()
        logger.info("Enum Trie built")

        # 初始化 ES 索引。默认只使用现有索引，避免服务启动或组件热重载时自动改写 RAG ES。
        try:
            self._init_index(force_reindex)
        except Exception as exc:
            self.es_available = False
            logger.warning(f"Elasticsearch unavailable, field registry will run without ES indexing: {exc}")

    # ==================== Trie 枚举检索 ====================

    def _build_enum_trie(self) -> _TrieNode:
        """将所有意图的枚举值插入 Trie 树，构建枚举→意图的快速查找结构。"""
        root = _TrieNode()
        for intent in self.intents:
            enum_vals = intent.get("enum") or []
            for val in enum_vals:
                val = str(val).strip()
                if not val:
                    continue
                node = root
                for ch in val:
                    if ch not in node.children:
                        node.children[ch] = _TrieNode()
                    node = node.children[ch]
                # 同一枚举值可能对应多个意图，去重后追加
                if intent not in node.intents:
                    node.intents.append(intent)
        return root

    def retrieve_by_enum(self, query: str) -> List[Dict[str, Any]]:
        """
        用 Trie 树扫描查询字符串，找出所有命中枚举值的意图。

        遍历查询的每个起始位置，沿 Trie 最长匹配，收集所有命中的意图（去重）。
        时间复杂度 O(|query| × max_enum_len)，全内存操作，无网络开销。
        """
        matched: Dict[str, Dict] = {}   # intent_id → intent，用于去重
        n = len(query)
        root = self._enum_trie

        startTime = time.perf_counter()

        for start in range(n):
            node = root
            for end in range(start, n):
                ch = query[end]
                if ch not in node.children:
                    break
                node = node.children[ch]
                for intent in node.intents:
                    iid = intent.get("id", intent.get("field", ""))
                    if iid not in matched:
                        matched[iid] = intent

        results = list(matched.values())
        # results = self._filter_trie_intents_by_context(query, results)
        if results:
            logger.debug(
                f"Trie matched {len(results)} intents for query '{query}': "
                f"{[r.get('id') for r in results]}"
                f"cost_times: {time.perf_counter() - startTime}"
            )
        return results

    def _filter_trie_intents_by_context(self, query: str, intents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        对高歧义的客户本人/家庭成员字段做最小上下文过滤。

        第一阶段仅处理最容易串召回的几组字段：
        - clientSex / familyInfo.familyclientsex
        - clientAge / familyInfo.familyclientage
        - clientBirthday / familyInfo.familyclientbirthday
        """
        family_markers = ("家庭成员", "家里", "子女", "父母", "配偶", "儿子", "女儿", "孩子", "家属")
        has_family_context = any(marker in query for marker in family_markers)

        family_fields = {"familyInfo.familyclientsex", "familyInfo.familyclientage", "familyInfo.familyclientbirthday"}
        client_fields = {"clientSex", "clientAge", "clientBirthday"}

        filtered: List[Dict[str, Any]] = []
        for intent in intents:
            field = str(intent.get("field", "")).strip()
            if has_family_context and field in client_fields:
                continue
            if not has_family_context and field in family_fields:
                continue
            filtered.append(intent)
        return filtered

    def retrieve_by_fields(self, fields: List[str]) -> List[Dict[str, Any]]:
        """按字段名直接返回对应的 intent 定义，保持 field_definitions 中的原始顺序。"""
        if not fields:
            return []

        wanted = {str(field).strip() for field in fields if str(field).strip()}
        if not wanted:
            return []

        return [
            intent for intent in self.intents
            if str(intent.get("field", "")).strip() in wanted
        ]

    def retrieve_by_field_operator_pairs(self, pairs: List[tuple[str, str]]) -> List[Dict[str, Any]]:
        """按 field+operator 返回对应的 intent 定义，保持 field_definitions 中的原始顺序。"""
        if not pairs:
            return []

        wanted = {
            (str(field).strip(), str(operator).strip())
            for field, operator in pairs
            if str(field).strip() and str(operator).strip()
        }
        if not wanted:
            return []

        seen: set[tuple[str, str]] = set()
        results: List[Dict[str, Any]] = []
        for intent in self.intents:
            key = (
                str(intent.get("field", "")).strip(),
                str(intent.get("operator", "")).strip(),
            )
            if key not in wanted or key in seen:
                continue
            results.append(intent)
            seen.add(key)
        return results

    # ==================== 初始化 ====================

    def _load_yaml(self) -> List[Dict[str, Any]]:
        with open(self.yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 加载 config/enums/ 目录下所有 yaml 文件，用于展开 enum_ref
        enum_dict: Dict[str, List] = {}
        enums_dir = Path(settings.ENUMS_DIR_PATH)

        for enum_file in sorted(enums_dir.glob("*_enums_args.yaml")):
            with open(enum_file, "r", encoding="utf-8") as ef:
                raw = yaml.safe_load(ef) or {}
            for k, entry in raw.items():
                vals = entry.get("values", []) if isinstance(entry, dict) else list(entry)
                enum_dict[k] = [str(v) for v in vals]

        # 展开 enum_ref → enum
        for intent in data.get("intents", []):
            if "enum_ref" in intent and not intent.get("enum"):
                intent["enum"] = enum_dict.get(intent["enum_ref"], [])

        return data.get("intents", [])

    def _compute_intents_fingerprint(self, intents: List[Dict[str, Any]]) -> str:
        """根据当前 field_definitions 内容生成稳定指纹，用于 ES 索引刷新判断。"""
        payload = json.dumps(intents, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.md5(payload.encode("utf-8")).hexdigest()

    def _init_index(self, force_reindex: bool):
        """检查索引是否存在；只有强制重建时才写入 ES。"""
        exists = self.es.indices.exists(index=self.index)

        if not force_reindex:
            if exists:
                logger.info(f"Using existing ES index '{self.index}' without startup reindex")
            else:
                self.es_available = False
                logger.warning(
                    f"ES index '{self.index}' does not exist; call /api/v1/fields/reindex to build it"
                )
            return

        # 删除旧索引
        if exists:
            self.es.indices.delete(index=self.index)
            logger.info(f"Deleted old index '{self.index}'")

        # 创建索引（尝试 IK，失败则降级到 standard）
        mapping = _build_index_mapping(settings.ES_ANALYZER, self._intents_fingerprint)
        try:
            self.es.indices.create(index=self.index, body=mapping)
            logger.info(f"Created ES index '{self.index}' with analyzer '{settings.ES_ANALYZER}'")
        except Exception as e:
            if "ik" in settings.ES_ANALYZER or "smartcn" in settings.ES_ANALYZER:
                logger.warning(
                    f"Analyzer '{settings.ES_ANALYZER}' not available ({e}), falling back to 'standard'"
                )
                mapping = _build_index_mapping("standard", self._intents_fingerprint)
                self.es.indices.create(index=self.index, body=mapping)
                logger.info(f"Created ES index '{self.index}' with analyzer 'standard'")
            else:
                raise

        # 批量写入
        actions = [
            {
                "_index": self.index,
                "_id": intent.get("id", str(i)),
                "_source": {
                    "id":             intent.get("id", ""),
                    "field":          intent.get("field", ""),
                    "operator":       intent.get("operator", ""),
                    "value_type":     intent.get("value_type", ""),
                    "retrieval_text": intent.get("retrieval_text", ""),
                    "description":    intent.get("description", ""),
                    "notes":          intent.get("notes", ""),
                    "examples_text":  self._flatten_examples_text(intent.get("examples", [])),
                    "negative_examples_text": self._flatten_negative_examples_text(
                        intent.get("negative_examples", [])
                    ),
                    "enum":           intent.get("enum", []),
                    "unit":           intent.get("unit", ""),
                    "format":         intent.get("format", ""),
                    "show_enum_in_prompt": intent.get("show_enum_in_prompt", True),
                    "enum_candidate_limit_in_prompt": intent.get("enum_candidate_limit_in_prompt", 5),
                    "examples":       intent.get("examples", []),
                    "negative_examples": intent.get("negative_examples", []),
                }
            }
            for i, intent in enumerate(self.intents)
        ]
        success, errors = bulk(self.es, actions, raise_on_error=False)
        if errors:
            logger.warning(f"Bulk index errors: {errors}")
        self.es.indices.refresh(index=self.index)
        logger.info(f"Indexed {success} intents into ES '{self.index}'")

    def _build_enum_metadata(self):
        """构建字段到枚举定义的映射，用于运行时标准化。"""
        for intent in self.intents:
            field = str(intent.get("field", "")).strip()
            if not field:
                continue
            enum_ref = str(intent.get("enum_ref", "")).strip()
            enum_vals = [str(v).strip() for v in (intent.get("enum") or []) if str(v).strip()]

            if enum_ref and field not in self._field_to_enum_ref:
                self._field_to_enum_ref[field] = enum_ref
            if enum_vals and field not in self._enum_values_by_field:
                self._enum_values_by_field[field] = enum_vals

    def _load_value_mappings(self):
        """加载口语别名 -> 标准枚举值映射。"""
        mappings_path = Path(settings.VALUE_MAPPINGS_PATH)
        if not mappings_path.exists():
            logger.warning(f"value_mappings.yaml not found: {mappings_path}")
            return

        with open(mappings_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        for key, mapping in raw.items():
            if not isinstance(mapping, dict):
                continue
            target_field = self._field_to_enum_ref.get(key, key)
            self._value_mappings[target_field] = {
                str(alias).strip(): str(value).strip()
                for alias, value in mapping.items()
                if str(alias).strip() and str(value).strip()
            }

    def _build_query_normalizer(self):
        """
        构建 query 级别的归一化替换表。

        目标：
        - 在解析前将口语别名统一成标准实体值
        - 使用单次 re.sub，避免级联替换
        - 长串优先，避免短别名先匹配破坏长实体
        """
        lookup: Dict[str, str] = {}

        for field_mappings in self._value_mappings.values():
            for alias, std in field_mappings.items():
                lookup[alias] = std
                # 自映射占位，避免标准值被其短前缀别名截断
                lookup.setdefault(std, std)

        aliases = sorted(lookup.keys(), key=len, reverse=True)
        if aliases:
            import re
            self._query_normalize_pattern = re.compile(
                "|".join(re.escape(alias) for alias in aliases)
            )
            self._query_normalize_lookup = lookup
        else:
            self._query_normalize_pattern = None
            self._query_normalize_lookup = {}

    def normalize_field_value(self, field: str, value: Any) -> Any:
        """
        按字段枚举定义将字符串值标准化为标准枚举值。

        仅处理字符串单值；范围/list/dict 直接原样返回。
        """
        if not isinstance(value, str):
            return value

        normalized = value.strip()
        if not normalized:
            return value

        enum_vals = self._enum_values_by_field.get(field, [])
        if normalized in enum_vals:
            return normalized

        mapped = self._value_mappings.get(field, {}).get(normalized)
        if mapped:
            logger.debug(f"Normalized enum value for field '{field}': '{value}' -> '{mapped}'")
            return mapped

        return value

    def normalize_query(self, query: str) -> str:
        """在解析前对 query 做 value_mapping 归一化。"""
        startTime = time.perf_counter()
        if not isinstance(query, str) or not query or not self._query_normalize_pattern:
            return query

        normalized = self._query_normalize_pattern.sub(
            lambda m: self._query_normalize_lookup.get(m.group(0), m.group(0)),
            query,
        )
        if normalized != query:
            logger.debug(f"Normalized query: '{query}' -> '{normalized}'")

        logger.info(f"{query}改写为：{normalized}，耗时：{time.perf_counter() - startTime}")
        return normalized

    # ==================== 检索 ====================

    def retrieve(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        从 ES 检索与查询最相关的字段意图

        使用 multi_match 在 retrieval_text（权重 3）、description（权重 2）和 notes（权重 1）上检索，
        BM25 打分，返回 top_k 个意图的完整原始 dict。
        """
        if not query.strip():
            return []

        startTime = time.perf_counter()

        if not getattr(self, "es_available", True):
            logger.warning("ES retrieval skipped because Elasticsearch is unavailable")
            return []

        normalized_query = self.normalize_query(query.strip())
        clauses = self._split_query_clauses_for_retrieval(normalized_query)
        retrieval_queries = [normalized_query]
        retrieval_queries.extend(clause for clause in clauses if clause != normalized_query)

        try:
            merged: Dict[str, Dict[str, Any]] = {}
            ordered_ids: List[str] = []

            for retrieval_query in retrieval_queries:
                resp = self.es.search(index=self.index, body=self._build_retrieve_body(retrieval_query, top_k))
                hits = resp["hits"]["hits"]
                for hit in hits:
                    source = hit["_source"]
                    intent_id = str(source.get("id", "")).strip() or str(source.get("field", "")).strip()
                    if intent_id in merged:
                        continue
                    merged[intent_id] = source
                    ordered_ids.append(intent_id)
                    if len(ordered_ids) >= top_k:
                        break
                if len(ordered_ids) >= top_k:
                    break

            results = [merged[intent_id] for intent_id in ordered_ids[:top_k]]
            logger.debug(
                f"ES retrieved {len(results)} intents for query '{normalized_query}': "
                f"{[r['id'] for r in results]}"
                f"cost_times = {time.perf_counter() - startTime}"
            )
            return results
        except Exception as e:
            logger.error(f"ES retrieval failed: {e}")
            return []

    def _build_retrieve_body(self, normalized_query: str, top_k: int) -> Dict[str, Any]:
        return {
            "query": {
                "bool": {
                    "should": [
                        {
                            "multi_match": {
                                "query": normalized_query,
                                "fields": [
                                    "retrieval_text^5",
                                    # "description^2",
                                    # "notes^1",
                                    # "examples_text^4",
                                    # "negative_examples_text^0.5",
                                ],
                                "type": "best_fields",
                                "operator": "or",
                                "minimum_should_match": "1",
                            }
                        },
                        {
                            "match_phrase": {
                                "retrieval_text": {
                                    "query": normalized_query,
                                    "boost": 8,
                                }
                            }
                        },
                        {
                            "match_phrase": {
                                "examples_text": {
                                    "query": normalized_query,
                                    "boost": 6,
                                }
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": top_k,
            "_source": True,
        }

    @staticmethod
    def _split_query_clauses_for_retrieval(query: str) -> List[str]:
        parts = [part.strip() for part in re.split(r"(?:、|，|,|；|;|并且|而且|且)", query) if part.strip()]
        return parts

    @staticmethod
    def _flatten_examples_text(examples: Any) -> str:
        if not isinstance(examples, list):
            return ""
        chunks: List[str] = []
        for example in examples:
            if not isinstance(example, dict):
                continue
            query = str(example.get("query", "")).strip()
            if query:
                chunks.append(query)
        return " ".join(chunks)

    @staticmethod
    def _flatten_negative_examples_text(examples: Any) -> str:
        if not isinstance(examples, list):
            return ""
        chunks: List[str] = []
        for example in examples:
            if not isinstance(example, dict):
                continue
            query = str(example.get("query", "")).strip()
            reason = str(example.get("reason", "")).strip()
            if query:
                chunks.append(query)
            if reason:
                chunks.append(reason)
        return " ".join(chunks)

    # ==================== 格式化 ====================

    def _infer_enum_candidates_for_prompt(
        self,
        field: str,
        enum_vals: List[str],
        query: str,
        limit: int = 3,
    ) -> List[str]:
        """根据 query 为大枚举字段挑选少量候选值，避免全量枚举灌入 prompt。"""
        if not enum_vals or not query:
            return []

        candidates: List[str] = []
        seen = set()

        for enum_val in enum_vals:
            if enum_val in query and enum_val not in seen:
                candidates.append(enum_val)
                seen.add(enum_val)

        field_mappings = getattr(self, "_value_mappings", {}).get(field, {})
        for alias, std in field_mappings.items():
            if alias in query and std in enum_vals and std not in seen:
                candidates.append(std)
                seen.add(std)

        return candidates[:limit]

    def format_prompt_section(
        self, intents: List[Dict[str, Any]], query: str = "", max_chars: int = 0,
    ) -> str:
        """将检索到的意图格式化为 LLM prompt 中的字段参考段落

        Args:
            intents: 检索到的意图列表
            query: 用户原始查询（用于枚举候选推断）
            max_chars: 段落最大字符数，0=不限制；超限时逐级降级：
                       L1 枚举上限减半(12→6)保留示例 → L2 去示例保留说明
        """
        if not intents:
            return ""

        result = "\n\n".join(
            self._build_prompt_lines(intents, query, include_extras=True))
        if max_chars > 0 and len(result) > max_chars:
            logger.debug(
                f"Prompt section {len(result)} chars exceeds budget {max_chars}, "
                f"L1: reducing enum limit"
            )
            result = "\n\n".join(
                self._build_prompt_lines(
                    intents, query, include_extras=True, enum_limit_override=6))

        if max_chars > 0 and len(result) > max_chars:
            logger.debug(
                f"Prompt section {len(result)} chars still exceeds budget {max_chars}, "
                f"L2: dropping examples"
            )
            result = "\n\n".join(
                self._build_prompt_lines(
                    intents, query, include_extras=False, enum_limit_override=6))

        return result

    def _build_prompt_lines(
        self, intents: List[Dict[str, Any]], query: str, include_extras: bool,
        enum_limit_override: Optional[int] = None,
    ) -> List[str]:
        """构建 prompt 行列表"""
        lines = ["### 相关字段参考（根据查询内容动态召回）\n"]
        intents_by_id = getattr(self, "_intents_by_id", {})
        for intent in intents:
            source_intent = intents_by_id.get(str(intent.get("id", "")).strip(), {})
            merged_intent = dict(source_intent)
            merged_intent.update(intent)

            field = merged_intent.get("field", "")
            supported_ops = merged_intent.get("supported_operators", [])
            op = ", ".join(supported_ops) if supported_ops else merged_intent.get("operator", "")
            vtype = merged_intent.get("value_type", "")
            description = merged_intent.get("description", "")
            notes = merged_intent.get("notes", "")

            enum_values_by_field = getattr(self, "_enum_values_by_field", {})
            enum_vals = merged_intent.get("enum", []) or enum_values_by_field.get(field, [])
            show_enum_in_prompt = merged_intent.get("show_enum_in_prompt", True)
            enum_candidate_limit = int(merged_intent.get("enum_candidate_limit_in_prompt", 5))
            # 有序枚举需全量展示，LLM 才能正确做"以上/以下"展开
            is_ordered_enum = merged_intent.get("enum_ordered", False)
            unit = merged_intent.get("unit", "")
            fmt = merged_intent.get("format", "")

            parts = [f"- **{field}** | 操作符: {op} | 值类型: {vtype}"]
            # 枚举覆盖过滤：query 命中值优先展示，其余追加到上限
            if enum_vals and query and (settings.L4_ENUM_OVERLAP_FILTER or not show_enum_in_prompt):
                candidates = self._infer_enum_candidates_for_prompt(
                    field=field,
                    enum_vals=enum_vals,
                    query=query,
                    limit=enum_candidate_limit,
                )
            else:
                candidates = []
            candidate_set = set(candidates)

            if show_enum_in_prompt and enum_vals:
                if is_ordered_enum:
                    # 有序枚举全量展示，LLM 才能正确做"以上/以下"展开
                    parts.append(f"| 枚举: {enum_vals}")
                elif settings.L4_ENUM_OVERLAP_FILTER:
                    show_limit = int(merged_intent.get("show_enum_limit_in_prompt", 12))
                    if enum_limit_override is not None:
                        show_limit = min(show_limit, enum_limit_override)
                    if candidates:
                        # 命中枚举优先展示，其余枚举追加到上限
                        remaining = [v for v in enum_vals if v not in candidate_set]
                        display = candidates + remaining[:max(0, show_limit - len(candidates))]
                        parts.append(f"| 枚举: {display}")
                    else:
                        # show_enum_in_prompt: true 即使无命中也截断，避免大枚举灌入
                        parts.append(f"| 枚举: {enum_vals[:show_limit]}")
                else:
                    # 开关关闭：全量展示（旧行为）
                    parts.append(f"| 枚举: {enum_vals}")
            elif candidates:
                parts.append(f"| 候选枚举: {candidates}")
            if unit:
                parts.append(f"| 单位: {unit}")
            if fmt:
                parts.append(f"| 格式: {fmt}")
            if description:
                parts.append(f"| 定义: {description}")
            if notes:
                parts.append(f"| 说明: {notes}")
            lines.append(" ".join(parts))

            if include_extras:
                for ex in (merged_intent.get("examples") or []):
                    lines.append(
                        f"  示例: \"{ex.get('query','')}\" → "
                        f"{self._format_example_output(ex.get('output'))}"
                    )
                for ex in (merged_intent.get("negative_examples") or []):
                    lines.append(
                        f"  反例: \"{ex.get('query','')}\" → 不输出该字段"
                        f"{'；原因: ' + ex.get('reason', '') if ex.get('reason') else ''}"
                    )

        return lines

    def _format_example_output(self, output: Any) -> str:
        """将 examples.output 格式化为紧凑、稳定的字符串，支持多条件结构。"""
        if output is None:
            return ""
        if isinstance(output, str):
            return output
        try:
            return json.dumps(output, ensure_ascii=False, separators=(", ", ": "))
        except TypeError:
            return str(output)

    @classmethod
    def _strip_time_from_intent_output(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return re.sub(r"(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}", r"\1", value)

    @classmethod
    def _normalize_intent_output_dates(cls, value: Any) -> Any:
        if isinstance(value, str):
            return cls._strip_time_from_intent_output(value)
        if isinstance(value, list):
            return [cls._normalize_intent_output_dates(item) for item in value]
        if isinstance(value, dict):
            return {key: cls._normalize_intent_output_dates(item) for key, item in value.items()}
        return value


# ==================== 全局单例 ====================

_registry: Optional[FieldRegistry] = None


def get_field_registry(force_reindex: bool = False) -> FieldRegistry:
    global _registry
    if _registry is None:
        _registry = FieldRegistry(force_reindex=force_reindex)
    return _registry
