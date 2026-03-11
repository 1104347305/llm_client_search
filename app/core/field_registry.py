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
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml
from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk
from loguru import logger

from config.settings import settings


# ES 索引 Mapping
def _build_index_mapping(analyzer: str) -> Dict[str, Any]:
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
                "notes": {
                    "type": "text",
                    "analyzer": index_analyzer,
                    "search_analyzer": search_analyzer,
                },
                "enum":     {"type": "keyword"},
                "unit":     {"type": "keyword"},
                "format":   {"type": "keyword"},
                "examples": {"type": "object", "enabled": False},
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
            yaml_path = str(
                Path(__file__).parent.parent.parent / "config" / "field_definitions.yaml"
            )
        self.yaml_path = yaml_path
        self.index = settings.ES_FIELD_INDEX

        # 构建 ES 客户端
        es_kwargs: Dict[str, Any] = {"hosts": [settings.ES_HOST]}
        if settings.ES_USERNAME and settings.ES_PASSWORD:
            es_kwargs["basic_auth"] = (settings.ES_USERNAME, settings.ES_PASSWORD)
        self.es = Elasticsearch(**es_kwargs)

        # 加载意图数据
        self.intents: List[Dict[str, Any]] = self._load_yaml()
        logger.info(f"Loaded {len(self.intents)} intents from {yaml_path}")

        # 构建枚举值 Trie 树（用于快速枚举命中检索）
        self._enum_trie = self._build_enum_trie()
        logger.info("Enum Trie built")

        # 初始化 ES 索引
        self._init_index(force_reindex)

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
        if results:
            logger.debug(
                f"Trie matched {len(results)} intents for query '{query}': "
                f"{[r.get('id') for r in results]}"
            )
        return results

    # ==================== 初始化 ====================

    def _load_yaml(self) -> List[Dict[str, Any]]:
        with open(self.yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("intents", [])

    def _init_index(self, force_reindex: bool):
        """检查索引是否存在，按需创建并导入数据"""
        exists = self.es.indices.exists(index=self.index)

        if exists and not force_reindex:
            count = self.es.count(index=self.index)["count"]
            if count == len(self.intents):
                logger.info(f"ES index '{self.index}' already up-to-date ({count} docs)")
                return
            logger.info(f"ES index doc count mismatch ({count} vs {len(self.intents)}), re-indexing...")

        # 删除旧索引
        if exists:
            self.es.indices.delete(index=self.index)
            logger.info(f"Deleted old index '{self.index}'")

        # 创建索引（尝试 IK，失败则降级到 standard）
        mapping = _build_index_mapping(settings.ES_ANALYZER)
        try:
            self.es.indices.create(index=self.index, body=mapping)
            logger.info(f"Created ES index '{self.index}' with analyzer '{settings.ES_ANALYZER}'")
        except Exception as e:
            if "ik" in settings.ES_ANALYZER or "smartcn" in settings.ES_ANALYZER:
                logger.warning(
                    f"Analyzer '{settings.ES_ANALYZER}' not available ({e}), falling back to 'standard'"
                )
                mapping = _build_index_mapping("standard")
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
                    "notes":          intent.get("notes", ""),
                    "enum":           intent.get("enum", []),
                    "unit":           intent.get("unit", ""),
                    "format":         intent.get("format", ""),
                    "examples":       intent.get("examples", []),
                }
            }
            for i, intent in enumerate(self.intents)
        ]
        success, errors = bulk(self.es, actions, raise_on_error=False)
        if errors:
            logger.warning(f"Bulk index errors: {errors}")
        self.es.indices.refresh(index=self.index)
        logger.info(f"Indexed {success} intents into ES '{self.index}'")

    # ==================== 检索 ====================

    def retrieve(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        从 ES 检索与查询最相关的字段意图

        使用 multi_match 在 retrieval_text（权重 3）和 notes（权重 1）上检索，
        BM25 打分，返回 top_k 个意图的完整原始 dict。
        """
        if not query.strip():
            return []

        body = {
            "query": {
                "multi_match": {
                    "query": query,
                    "fields": ["retrieval_text^3", "notes^1"],
                    "type": "best_fields",
                    "operator": "or",
                    "minimum_should_match": "1",
                }
            },
            "size": top_k,
            "_source": True,
        }

        try:
            resp = self.es.search(index=self.index, body=body)
            hits = resp["hits"]["hits"]
            results = [hit["_source"] for hit in hits]
            logger.debug(
                f"ES retrieved {len(results)} intents for query '{query}': "
                f"{[r['id'] for r in results]}"
            )
            return results
        except Exception as e:
            logger.error(f"ES retrieval failed: {e}")
            return []

    # ==================== 格式化 ====================

    def format_prompt_section(self, intents: List[Dict[str, Any]]) -> str:
        """将检索到的意图格式化为 LLM prompt 中的字段参考段落"""
        if not intents:
            return ""

        lines = ["### 相关字段参考（根据查询内容动态召回）\n"]
        for intent in intents:
            field = intent.get("field", "")
            op = intent.get("operator", "")
            vtype = intent.get("value_type", "")
            notes = intent.get("notes", "")
            enum_vals = intent.get("enum", [])
            unit = intent.get("unit", "")
            fmt = intent.get("format", "")

            parts = [f"- **{field}** | 操作符: {op} | 值类型: {vtype}"]
            if enum_vals:
                parts.append(f"| 枚举: {enum_vals}")
            if unit:
                parts.append(f"| 单位: {unit}")
            if fmt:
                parts.append(f"| 格式: {fmt}")
            if notes:
                parts.append(f"| 说明: {notes}")
            lines.append(" ".join(parts))

            for ex in (intent.get("examples") or [])[:2]:
                lines.append(f"  示例: \"{ex.get('query','')}\" → {ex.get('output','')}")

        return "\n".join(lines)


# ==================== 全局单例 ====================

_registry: Optional[FieldRegistry] = None


def get_field_registry(force_reindex: bool = False) -> FieldRegistry:
    global _registry
    if _registry is None:
        _registry = FieldRegistry(force_reindex=force_reindex)
    return _registry
