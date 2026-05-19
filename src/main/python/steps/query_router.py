"""
查询路由器 - 四层串联漏斗
L1 → L2 → L3 依次执行并累积条件；三层均无条件时转至 L4 (LLM)
"""
from dataclasses import dataclass, field
import asyncio
from loguru import logger
from src.main.python.models.schemas import ParsedQuery, QueryLogic, LogicNode, Condition, Operator, RangeValue
from src.main.python.steps.level1_rule_engine import Level1RuleEngine
from src.main.python.steps.level2_enhanced_matcher import Level2EnhancedMatcher
from src.main.python.steps.level3_semantic_cache import Level3SemanticCache
from src.main.python.steps.level4_llm_parser import Level4LLMParser
from src.main.python.steps.field_registry import FieldRegistry, get_field_registry
from src.main.python.config.settings import settings
from src.main.python.models.field_mapping import get_query_field, QUERY_FIELDS
from typing import List, Tuple, Optional, Set, Dict, Any
from pathlib import Path
import re
import yaml
from src.main.python.utils.sensitive_masking import mask_for_log
from src.main.python.utils.name_candidate import detect_name_candidate, looks_like_full_person_name, NameCandidate
from sympy.integrals.manualintegrate import rewriter


@dataclass
class _RouteState:
    rewritten_query: Optional[str] = None
    matched_patterns: List[Dict[str, Any]] = field(default_factory=list)
    name_candidate: Optional[NameCandidate] = None


class QueryRouter:
    """查询路由器 - 四层串联漏斗"""

    _SEARCH_PREFIX_PATTERN = (
        r"(?:(?:查找|查询|查|找|找一下|查一下|检索|搜索|帮我查|帮我找|帮我搜索|"
        r"给我看看|帮我看看|看看|哪些是|谁是)(?:一下|下)?(?:[，, ]{0,2}))?"
    )
    _CLIENT_FULL_NAME_PATTERNS = [
        re.compile(
            _SEARCH_PREFIX_PATTERN +
            r"(?:的客户|客户)?(?:叫|名叫|叫做|姓名是|姓名为|名字是|客户叫)([\u4e00-\u9fa5]{2,4})(?:的客户|客户)?$"
        ),
        re.compile(
            _SEARCH_PREFIX_PATTERN +
            r"([\u4e00-\u9fa5]{2,4})(?:的客户|客户|本人)$"
        ),
    ]
    _CLIENT_NAME_EXCLUDED_CONTEXTS = (
        "家庭成员", "家属", "成员", "子女", "父母", "配偶", "儿子", "女儿", "孩子",
        "投保人", "被保人", "被保险人", "受益人", "联系人",
    )

    def __init__(self, field_registry: Optional[FieldRegistry] = None):
        self.level1 = Level1RuleEngine()
        self.level2 = Level2EnhancedMatcher()
        # self.level3 = Level3SemanticCache() if settings.ENABLE_L3 else None
        self.field_registry = field_registry or get_field_registry()
        self.level4 = Level4LLMParser(level2_recall=self.level2, field_registry=self.field_registry)

        # 加载已知字段和枚举值，用于 L4 输出后处理校验
        self._valid_fields: Set[str] = set()
        self._enum_values: Dict[str, List[str]] = {}
        self._field_time_formats: Dict[str, str] = {}
        self._load_validation_data()

        logger.info(
            f"Query router initialized | "
            f"L1={'ON' if settings.ENABLE_L1 else 'OFF'} "
            f"L2={'ON' if settings.ENABLE_L2 else 'OFF'} "
            f"L3={'ON' if settings.ENABLE_L3 else 'OFF'} "
            f"L4={'ON' if settings.ENABLE_L4 else 'OFF'} "
            f"已知字段={len(self._valid_fields)}"
        )
        self._last_rewritten_query: Optional[str] = None
        self._last_matched_patterns: List[Dict[str, str]] = []
        self._last_name_candidate: Optional[NameCandidate] = None

    @staticmethod
    def _condition_merge_key(condition: Condition) -> Tuple[str, str]:
        return condition.field, condition.operator.value

    def _merge_l2_candidate_conditions(
        self,
        conditions: List[Condition],
        l2_candidate_conditions: List[Condition],
        strategy: str = "l2_priority",
    ) -> List[Condition]:
        """
        用 L2 候选条件合并到 L4 结果。

        strategy:
          - "llm_only": 不合并，直接返回 conditions
          - "l2_priority": L2 覆盖 LLM + 补齐遗漏（原行为）
          - "llm_priority": LLM 优先 + L2 补齐遗漏

        只做字段级合并，不改变原有 query_logic。
        """
        if not l2_candidate_conditions or strategy == "llm_only":
            return conditions

        candidate_map = {
            self._condition_merge_key(cond): cond
            for cond in l2_candidate_conditions
        }
        merged: List[Condition] = []
        used_keys: Set[Tuple[str, str]] = set()

        for cond in conditions:
            key = self._condition_merge_key(cond)
            if strategy == "l2_priority" and key in candidate_map:
                # L2 覆盖 LLM
                merged.append(candidate_map[key])
                used_keys.add(key)
                continue
            if strategy == "llm_priority" and key in candidate_map:
                # LLM 优先，但仍记录 L2 key 避免重复补齐
                merged.append(cond)
                used_keys.add(key)
                continue
            merged.append(cond)

        # 补齐 L4 漏掉的条件（所有非 llm_only 策略都补齐）
        for key, candidate in candidate_map.items():
            if key not in used_keys:
                merged.append(candidate)

        return self._deduplicate_merged_conditions(merged)

    @staticmethod
    def _deduplicate_merged_conditions(conditions: List[Condition]) -> List[Condition]:
        """去除合并后重复 value 的条件。"""
        seen_values: list = []
        result: List[Condition] = []
        for cond in conditions:
            value = cond.value
            values = []
            if not isinstance(value, list):
                values.append(value)
            else:
                values.extend(value)

            is_dup = False
            for v in values:
                if v in seen_values:
                    is_dup = True
                    break

            if is_dup:
                continue

            result.append(cond)
            if isinstance(value, list):
                seen_values.extend(value)
            else:
                seen_values.append(value)

        return result

    @staticmethod
    def _run_level2_match_sync(level2: Level2EnhancedMatcher, query: str) -> Tuple[List[Condition], List[Dict[str, Any]]]:
        """在线程中执行 L2 正则匹配，避免同步正则循环阻塞事件循环。"""
        conditions = asyncio.run(level2.match(query))
        matched_patterns = list(getattr(level2, "_last_matched_patterns", []))
        return conditions, matched_patterns

    async def _match_level2(self, query: str) -> Tuple[List[Condition], List[Dict[str, Any]]]:
        return await asyncio.to_thread(self._run_level2_match_sync, self.level2, query)

    async def _recall_level2_candidate_conditions(
        self,
        query: str,
        *,
        merge_to_llm_only: bool = False,
    ) -> List[Condition]:
        return await asyncio.to_thread(
            self.level2.recall_candidate_conditions,
            query,
            merge_to_llm_only=merge_to_llm_only,
        )

    @classmethod
    def _looks_like_full_person_name(cls, candidate: str) -> bool:
        return looks_like_full_person_name(candidate)

    @classmethod
    def _extract_explicit_client_full_name(cls, query: str) -> Optional[str]:
        if any(marker in query for marker in cls._CLIENT_NAME_EXCLUDED_CONTEXTS):
            return None
        if "姓" in query or "姓氏" in query:
            return None

        for pattern in cls._CLIENT_FULL_NAME_PATTERNS:
            match = pattern.fullmatch(query)
            if not match:
                continue
            candidate = match.group(1).strip()
            if cls._looks_like_full_person_name(candidate):
                return candidate
        return None

    def _enforce_explicit_client_full_name(self, query: str, conditions: List[Condition]) -> List[Condition]:
        """显式客户全名查询命中时，强制保留完整姓名，防止 LLM/L2 退化成单姓或漏解析。"""
        full_name = self._extract_explicit_client_full_name(query)
        if not full_name:
            return conditions

        normalized_conditions: List[Condition] = []
        has_exact_name = False
        for cond in conditions:
            if cond.field == get_query_field("customer_name") and cond.operator == Operator.MATCH:
                if cond.value == full_name:
                    has_exact_name = True
                    normalized_conditions.append(cond)
                continue
            normalized_conditions.append(cond)

        if not has_exact_name and len(conditions) == 0:
            normalized_conditions.append(
                Condition(
                    field=get_query_field("customer_name"),
                    operator=Operator.MATCH,
                    value=full_name,
                )
            )
        return normalized_conditions

    def _record_bare_name_candidate(self, query: str, state: Optional[_RouteState] = None) -> None:
        candidate = detect_name_candidate(query)
        if state is None:
            self._last_name_candidate = candidate if candidate.is_candidate else None
            patterns = self._last_matched_patterns
        else:
            state.name_candidate = candidate if candidate.is_candidate else None
            patterns = state.matched_patterns
        if not candidate.is_candidate:
            return
        patterns.append({
            "rule_name": "疑似姓名候选",
            "pattern": "surname+len(2-3|compound-4)",
            "matched_text": candidate.text,
            "match_type": "candidate",
            "confidence": candidate.confidence,
            "needs_verification": candidate.needs_verification,
            "reason": candidate.reason,
        })

    def _build_bare_value_weak_result(self, query: str, state: Optional[_RouteState] = None) -> ParsedQuery:
        """L1/L2 均无法确认字段时，将裸值扩成候选字段 OR。"""
        conditions = self.level2.build_bare_value_weak_conditions(query)
        confidence = self.level2.bare_value_weak_confidence()
        matched_patterns = state.matched_patterns if state is not None else self._last_matched_patterns
        matched_patterns.append({
            "rule_name": "裸值弱命",
            "pattern": self.level2.bare_value_weak_match.get("pattern"),
            "matched_text": query,
            "match_type": "bare_value_candidate",
            "confidence": confidence,
            "reason": "L1/L2 未命中完整格式，按可能字段 OR 查询",
        })
        final_conditions = self._finalize_conditions(query, conditions, state)
        return ParsedQuery(
            conditions=final_conditions,
            query_logic=QueryLogic.OR,
            logic_tree=None,
            confidence=confidence,
            matched_level=2,
            rewritten_query=state.rewritten_query if state is not None else self._last_rewritten_query,
            matched_patterns=matched_patterns,
        )

    def _materialize_name_candidate_if_needed(
        self,
        conditions: List[Condition],
        state: Optional[_RouteState] = None,
    ) -> List[Condition]:
        """仅在最终无任何条件时，才把疑似姓名候选升级为正式姓名条件。"""
        if conditions:
            return conditions
        name_candidate = state.name_candidate if state is not None else self._last_name_candidate
        if not name_candidate or not name_candidate.is_candidate:
            return conditions
        return [
            Condition(
                field=get_query_field("customer_name"),
                operator=Operator.MATCH,
                value=name_candidate.text,
            )
        ]

    def _finalize_conditions(
        self,
        query: str,
        conditions: List[Condition],
        state: Optional[_RouteState] = None,
    ) -> List[Condition]:
        """统一收口条件后处理，供普通链路和裸值弱命中链路复用。"""
        finalized = self._enforce_explicit_client_full_name(query, conditions)
        finalized = self._materialize_name_candidate_if_needed(finalized, state)
        finalized = self._validate_conditions(finalized)
        finalized = self.normalize_date_condition_formats(finalized)
        return self.normalize_conditions_for_summary(finalized)

    def _load_validation_data(self):
        """从配置指定的 field_definitions 和 enums 目录加载校验基准"""
        # 1. 从 field_definitions.yaml 收集合法字段名
        fd_path = Path(settings.FIELD_DEFINITIONS_PATH)
        if fd_path.exists():
            data = yaml.safe_load(fd_path.read_text(encoding='utf-8')) or {}
            for intent in data.get('intents', []):
                self._valid_fields.add(intent['field'])
        # 2. 从配置指定的 enums 目录收集枚举值
        enums_dir = Path(settings.ENUMS_DIR_PATH)
        value_mappings_path = Path(settings.VALUE_MAPPINGS_PATH).resolve()
        for f in sorted(enums_dir.glob('*_enums_args.yaml')):
            if f.resolve() == value_mappings_path:
                continue
            raw = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
            for field, entry in raw.items():
                vals = entry.get('values', []) if isinstance(entry, dict) else list(entry)
                if vals:
                    self._enum_values[field] = [str(v) for v in vals]

        self._field_time_formats = self._load_field_time_formats()

    def _load_field_time_formats(self) -> Dict[str, str]:
        """从 field_enums_args.yaml 加载字段日期/时间格式配置。"""
        field_enums_path = Path(settings.ENUMS_DIR_PATH) / "field_enums_args.yaml"
        if not field_enums_path.exists():
            logger.warning(f"field time format config not found: {field_enums_path}")
            return {}

        raw = yaml.safe_load(field_enums_path.read_text(encoding='utf-8')) or {}
        configured = raw.get("date_field_formats", {})
        if not isinstance(configured, dict):
            logger.warning("field_enums_args.yaml 中 date_field_formats 不是字典，已忽略")
            return {}

        supported_formats = {"yyyy-MM-dd", "yyyy-MM-dd HH:mm:ss"}
        formats: Dict[str, str] = {}
        for field, fmt in configured.items():
            field_name = str(field).strip()
            format_text = str(fmt).strip()
            if not field_name:
                continue
            if format_text not in supported_formats:
                logger.warning(
                    f"字段 '{field_name}' 的时间格式 '{format_text}' 暂不支持，"
                    f"仅支持 {sorted(supported_formats)}"
                )
                continue
            formats[field_name] = format_text
        return formats

    def normalize_conditions_for_summary(self, conditions: list[Condition]) -> list[Condition]:
        '''在意图摘要前缀轻量归并：GTE+LTE→RANGE，单值CONTAINS→MATCH。'''
        if not conditions:
            return []

        normalized: list[Condition] = []
        for cond in conditions:
            # 单值 CONTAINS / NOT_CONTAINS → MATCH / NOT_MATCH... 实际 NOT_CONTAINS 无对应单值操作符，仅处理 CONTAINS
            if cond.operator == Operator.CONTAINS and isinstance(cond.value, list) and len(cond.value) == 1:
                normalized.append(Condition(
                    field=cond.field,
                    operator=Operator.MATCH,
                    value=cond.value[0],
                ))
                continue
            normalized.append(cond)
        range_fields = {
            cond.field
            for cond in normalized
            if cond.operator == Operator.RANGE
        }
        if not range_fields:
            range_fields = set()

        _BOUND_OPS = (Operator.GT, Operator.GTE, Operator.LT, Operator.LTE)

        grouped_bounds: dict[str, dict[str, tuple[int, Condition]]] = {}
        for idx, cond in enumerate(normalized):
            if cond.field in range_fields:
                continue
            if cond.operator not in _BOUND_OPS:
                continue
            if cond.value is None or isinstance(cond.value, (list, dict, RangeValue)):
                continue

            bucket = grouped_bounds.setdefault(cond.field, {})
            key = cond.operator.value
            if key not in bucket:
                bucket[key] = (idx, cond)

        consumed_indices: set[int] = set()
        replacements: dict[int, Condition] = {}

        for field, bounds in grouped_bounds.items():
            lo_item = bounds.get(Operator.GTE.value) or bounds.get(Operator.GT.value)
            hi_item = bounds.get(Operator.LTE.value) or bounds.get(Operator.LT.value)
            if not lo_item or not hi_item:
                continue

            lo_idx, lo_cond = lo_item
            hi_idx, hi_cond = hi_item
            start_idx = min(lo_idx, hi_idx)
            replacements[start_idx] = Condition(
                field=field,
                operator=Operator.RANGE,
                value=RangeValue(min=lo_cond.value, max=hi_cond.value),
            )
            consumed_indices.update({lo_idx, hi_idx})

        if not replacements:
            return normalized

        merged: list[Condition] = []
        for idx, cond in enumerate(normalized):
            replacement = replacements.get(idx)
            if replacement is not None:
                merged.append(replacement)
                continue
            if idx in consumed_indices:
                continue
            merged.append(cond)
        return merged

    async def route_with_peeling(self, query: str, trace_id: str) -> ParsedQuery:
        """
        串联流水线路由：
        1. L1 处理原始查询，提取确定性实体
        2. L2 处理原始查询，提取模板条件
        3. L3 对原始查询检索语义缓存
        4. 若 L1+L2+L3 合计条件为空，则转至 L4 (LLM)
        """
        original_query = query
        logger.info(f"{trace_id}--->Routing query: {mask_for_log(original_query)}")
        query = query.replace(' ', '').replace('。', '')
        normalized_query = self.field_registry.normalize_query(query)
        if normalized_query != query:
            logger.info(f"{trace_id}--->Query normalized: '{mask_for_log(query)}' -> '{mask_for_log(normalized_query)}'")
        query = normalized_query
        state = _RouteState(rewritten_query=query)
        self._record_bare_name_candidate(query, state)

        all_conditions = []

        # Level 1: 规则引擎 - 提取确定性实体
        l1_conditions = []
        if settings.ENABLE_L1:
            l1_conditions = await self.level1.extract(query)
            state.matched_patterns.extend(list(getattr(self.level1, "_last_matched_patterns", [])))
            logger.info(f"{trace_id}--->Level 1 extracted {len(l1_conditions)} conditions")
        else:
            logger.info(f"{trace_id}--->Level 1 DISABLED, skipped")

        # Level 2: 增强模板匹配 - 使用原始查询
        l2_conditions = []
        l2_candidate_conditions: List[Condition] = []
        if settings.ENABLE_L2:
            l2_conditions, l2_matched_patterns = await self._match_level2(query)
            l2_candidate_conditions = await self._recall_level2_candidate_conditions(query)
            state.matched_patterns.extend(l2_matched_patterns)
            logger.info(f"{trace_id}--->Level 2 matched {len(l2_conditions)} conditions")
        else:
            logger.info(f"{trace_id}--->Level 2 DISABLED, skipped")

        # 合并 L1 和 L2 条件：只要 L2 有结果，就完全丢弃 L1 条件
        if l2_conditions:
            l1_conditions_filtered = []
            logger.info(f"{trace_id}--->L2 matched, dropping all L1 conditions")
        else:
            l1_conditions_filtered = l1_conditions

        l2_fields = {cond.field for cond in l2_conditions}

        # 先添加 L1 未被覆盖的条件，再添加 L2 的条件
        all_conditions.extend(l1_conditions_filtered)
        all_conditions.extend(l2_conditions)

        logger.info(f"{trace_id}--->After L2 override: kept {len(l1_conditions_filtered)} from L1, added {len(l2_conditions)} from L2")

        # Level 3: 语义缓存 - 始终对原始查询检索
        cached = None
        # if settings.ENABLE_L3 and self.level3 is not None:
        #     cached = await self.level3.get(query)
        #     if cached:
        #         all_conditions.extend(cached.conditions)
        #         logger.info(f"Level 3 cache hit, added {len(cached.conditions)} conditions")
        # else:
        #     logger.info("Level 3 DISABLED, skipped")

        # L1+L2+L3 均无条件 → Level 4 (LLM)
        if not all_conditions:
            if hasattr(self.level2, "is_bare_value_weak_query") and self.level2.is_bare_value_weak_query(query):
                logger.info(f"{trace_id}--->No confirmed L1/L2 conditions for bare value, returning weak OR candidates")
                return self._build_bare_value_weak_result(query, state)

            if settings.ENABLE_L4:
                logger.info(f"{trace_id}--->No conditions from L1+L2+L3, falling back to Level 4 (LLM)")
                parsed = await self.level4.parse(query)
                # parsed = await self.level4.agent_parse(query)
                # parsed.conditions = self._convert_age_to_birthday(parsed.conditions)

                # L2-L4 合并控制：根据策略决定是否合并 L2 候选条件
                merge_strategy = settings.L4_L2_MERGE_STRATEGY
                # 向后兼容：ENABLE_RAGE_L2_CANDIDATES=true 且 strategy=llm_only 时使用 l2_priority
                if settings.ENABLE_RAGE_L2_CANDIDATES and merge_strategy == "llm_only":
                    merge_strategy = "l2_priority"
                    logger.info(f"{trace_id}--->L2-L4 merge: ENABLE_RAGE_L2_CANDIDATES=true, using l2_priority (backward compat)")

                if merge_strategy != "llm_only":
                    merge_conditions = await self._recall_level2_candidate_conditions(
                        query, merge_to_llm_only=True
                    )
                    if merge_conditions:
                        logger.info(
                            f"{trace_id}--->L2-L4 merge: applying {merge_strategy} with "
                            f"{trace_id}--->{len(merge_conditions)} merge_to_llm conditions"
                        )
                        parsed.conditions = self._merge_l2_candidate_conditions(
                            parsed.conditions, merge_conditions, strategy=merge_strategy
                        )
                    else:
                        logger.info(f"{trace_id}--->L2-L4 merge: no merge_to_llm conditions matched, skipping merge")
                else:
                    logger.info(f"{trace_id}--->L2-L4 merge: strategy=llm_only, skipping merge")

                parsed.conditions = self._enforce_explicit_client_full_name(query, parsed.conditions)
                parsed.conditions = self._materialize_name_candidate_if_needed(parsed.conditions, state)
                parsed.conditions = self._validate_conditions(parsed.conditions)
                parsed.conditions = self.normalize_conditions_for_summary(parsed.conditions)
                parsed.rewritten_query = state.rewritten_query
                parsed.matched_patterns = state.matched_patterns

                # if settings.ENABLE_L3 and self.level3 is not None:
                #     await self.level3.set(query, parsed)
                return parsed

            else:
                logger.warning(f"{trace_id}--->No conditions found and Level 4 DISABLED — returning empty result")
                return ParsedQuery(conditions=[], query_logic=QueryLogic.AND, confidence=0.0, matched_level=0)

        # 确定匹配层级与置信度
        if cached:
            matched_level, confidence = 3, cached.confidence
        elif l2_conditions:
            matched_level, confidence = 2, 0.95
        else:
            matched_level, confidence = 1, 1.0

        # 后处理：将年龄条件转换为出生日期条件
        # all_conditions = self._convert_age_to_birthday(all_conditions)
        all_conditions = self._enforce_explicit_client_full_name(query, all_conditions)
        all_conditions = self._materialize_name_candidate_if_needed(all_conditions, state)

        # 后处理，校验所有条件（字段名+枚举值），有非法条件则返回空
        all_conditions = self._validate_conditions(all_conditions)
        all_conditions = self.normalize_conditions_for_summary(all_conditions)

        return ParsedQuery(
            conditions=all_conditions,
            query_logic=QueryLogic.AND,
            logic_tree=None,
            confidence=confidence,
            matched_level=matched_level,
            rewritten_query=state.rewritten_query,
            matched_patterns=state.matched_patterns
        )

    def _validate_conditions(self, conditions: List[Condition]) -> List[Condition]:
        """
        校验所有层级输出的条件。若存在任何非法条件，返回空列表（避免条件缺失导致错误结果）。
        校验规则：
        - 字段名不在 field_definitions.yaml 中 → 整体返回空
        - 字段有枚举约束且值（字符串）不在枚举中 → 整体返回空
        - 同字段下若 EXISTS/NOT_EXISTS 与更具体条件共存，则移除 EXISTS/NOT_EXISTS
        """
        if not self._valid_fields:
            return conditions  # 未加载校验数据，跳过校验

        newConditions = []
        keys = []
        for cond in conditions:
            # key = cond.field + '_' + cond.operator
            # if key in keys:
            #     continue
            # 1. 校验字段名
            if cond.field not in self._valid_fields:
                logger.warning(
                    f"条件校验失败：非法字段 '{cond.field}'（值={cond.value!r}），返回空条件"
                )
                return []

            if cond.operator in {Operator.EXISTS, Operator.NOT_EXISTS}:
                newConditions.append(cond)
                continue

            # 2. 校验枚举值
            # enum_vals = self._enum_values.get(cond.field)
            # if enum_vals and isinstance(cond.value, str):
            #     if cond.value not in enum_vals:
            #         logger.warning(
            #             f"条件校验失败：字段 '{cond.field}' 的值非法，"
            #             f"错误值={cond.value!r}，合法枚举={enum_vals!r}，返回空条件"
            #         )
            #         return []
            # elif enum_vals and isinstance(cond.value, list):
            #     invalid_values = [value for value in cond.value if isinstance(value, str) and value not in enum_vals]
            #     if invalid_values:
            #         logger.warning(
            #             f"条件校验失败：字段 '{cond.field}' 的列表值存在非法项，"
            #             f"错误值={invalid_values!r}，原始值={cond.value!r}，合法枚举={enum_vals!r}，返回空条件"
            #         )
            #         return []

            # 符号值校验
            value = self._normalize_condition_value(cond.field, cond.operator, cond.value)
            cond.value = value
            newConditions.append(cond)
            # keys.append(key)

        field_to_ops: Dict[str, set[Operator]] = {}
        for cond in newConditions:
            field_to_ops.setdefault(cond.field, set()).add(cond.operator)

        normalized_conditions: List[Condition] = []
        for cond in newConditions:
            field_ops = field_to_ops.get(cond.field, set())
            if cond.operator == Operator.EXISTS and any(op != Operator.EXISTS for op in field_ops):
                continue
            if cond.operator == Operator.NOT_EXISTS and any(op != Operator.NOT_EXISTS for op in field_ops):
                continue
            normalized_conditions.append(cond)

        return normalized_conditions

    def _normalize_condition_value(self, field: str, operator: Operator, value: Any) -> Any:
        '''统一约束 Level2 输出的 value 结构'''
        if operator in [Operator.CONTAINS, Operator.NOT_CONTAINS]:
            if isinstance(value, list):
                return value
            return [value]

        if isinstance(value, list):
            if len(value) > 1:
                logger.warning(
                    f"Level2 produced list value for field='{field}' operator='{operator.value}'"
                    f"using first item only: {value}"
                )
                return value[0]

        return value

    @staticmethod
    def _coerce_date_text(value: Any) -> Optional[Tuple[str, Optional[str]]]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None

        match = re.match(
            r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?$",
            text,
        )
        if not match:
            return None

        year, month, day, hour, minute, second = match.groups()
        return (
            f"{int(year):04d}-{int(month):02d}-{int(day):02d}",
            f"{int(hour or 0):02d}:{int(minute or 0):02d}:{int(second or 0):02d}" if hour is not None else None,
        )

    def _normalize_date_scalar(
            self,
            field: str,
            operator: Operator,
            value: Any,
            bound: Optional[str] = None,
    ) -> Any:
        field_format = getattr(self, "_field_time_formats", {}).get(field)
        if field_format not in {"yyyy-MM-dd", "yyyy-MM-dd HH:mm:ss"}:
            return value

        coerced = self._coerce_date_text(value)
        if coerced is None:
            return value

        date_part, time_part = coerced
        if field_format == "yyyy-MM-dd":
            return date_part

        if time_part is not None:
            return f"{date_part} {time_part}"

        if bound == "min" or operator in {Operator.LT, Operator.LTE}:
            return f"{date_part} 23:59:59"
        return f"{date_part} 00:00:00"

    def normalize_date_condition_formats(self, conditions: List[Condition]) -> List[Condition]:
        """按 field_enums_args.yaml 中配置的字段时间格式纠正日期条件值。"""
        normalized: List[Condition] = []
        for cond in conditions:
            if cond.operator in {Operator.EXISTS, Operator.NOT_EXISTS}:
                normalized.append(cond)
                continue

            value = cond.value
            if cond.operator == Operator.RANGE:
                if isinstance(value, RangeValue):
                    value = RangeValue(
                        min=self._normalize_date_scalar(cond.field, cond.operator, value.min, bound="min"),
                        max=self._normalize_date_scalar(cond.field, cond.operator, value.max, bound="max"),
                    )
                elif isinstance(value, dict):
                    value = {
                        **value,
                        "min": self._normalize_date_scalar(cond.field, cond.operator, value.get("min"), bound="min"),
                        "max": self._normalize_date_scalar(cond.field, cond.operator, value.get("max"), bound="max"),
                    }
            else:
                value = self._normalize_date_scalar(cond.field, cond.operator, value)

            normalized.append(Condition(field=cond.field, operator=cond.operator, value=value))
        return normalized

    def convert_age_to_birthday(self, conditions: List[Condition], today=None) -> List[Condition]:
        """
        后处理：将年龄条件转换为出生日期范围条件。
        clientAge       → clientBirthday
        familyInfo.familyclientage  → familyInfo.familyclientbirthday

        逻辑（按真实周岁精确到天）：
        - GTE N  → birthday LTE 今天-N年 23:59:59（年龄越大，出生越早）
        - LTE N  → birthday GTE 今天-(N+1)年+1天 00:00:00
        - RANGE [min_age, max_age] → birthday RANGE
          [今天-(max_age+1)年+1天 00:00:00, 今天-min_age年 23:59:59]
        """
        from datetime import date, timedelta

        today = today or date.today()

        def _minus_years(base_date, years: int):
            try:
                return base_date.replace(year=base_date.year - years)
            except ValueError:
                # 处理 2 月 29 日落到非闰年的情况。
                return base_date.replace(year=base_date.year - years, day=28)

        def _start_of_day(value):
            return f"{value:%Y-%m-%d} 00:00:00"

        def _end_of_day(value):
            return f"{value:%Y-%m-%d} 23:59:59"

        def _birthday_range_for_age(age: int) -> RangeValue:
            earliest = _minus_years(today, age + 1) + timedelta(days=1)
            latest = _minus_years(today, age)
            return RangeValue(min=_start_of_day(earliest), max=_end_of_day(latest))

        age_field_map = {
            'familyInfo.familyclientage': 'familyInfo.familyclientbirthday'
        }

        result = []
        for cond in conditions:
            target_field = age_field_map.get(cond.field)
            if target_field is None:
                result.append(cond)
                continue
            v = cond.value
            try:
                if cond.operator == Operator.RANGE and isinstance(v, RangeValue):
                    min_age = int(v.min) if v.min is not None else 0
                    max_age = int(v.max) if v.max is not None else 120
                    if min_age > max_age:
                        min_age, max_age = max_age, min_age
                    earliest = _minus_years(today, max_age + 1) + timedelta(days=1)
                    latest = _minus_years(today, min_age)
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.RANGE,
                        value=RangeValue(
                            min=_start_of_day(earliest),
                            max=_end_of_day(latest),
                        ),
                    )
                elif cond.operator == Operator.GTE:
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.LTE,
                        value=_end_of_day(_minus_years(today, int(v))),
                    )
                elif cond.operator == Operator.LTE:
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.GTE,
                        value=_start_of_day(_minus_years(today, int(v) + 1) + timedelta(days=1)),
                    )
                elif cond.operator == Operator.GT:
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.LTE,
                        value=_end_of_day(_minus_years(today, int(v) + 1)),
                    )
                elif cond.operator == Operator.LT:
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.GTE,
                        value=_start_of_day(_minus_years(today, int(v)) + timedelta(days=1)),
                    )
                elif cond.operator == Operator.MATCH:
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.RANGE,
                        value=_birthday_range_for_age(int(v)),
                    )
                else:
                    result.append(cond)
                    continue
                logger.debug(
                    f"年龄→出生日期: {cond.field}({cond.operator.value}, {v}) "
                    f"→ {new_cond.field}({new_cond.operator.value}, {new_cond.value})"
                )
                result.append(new_cond)
            except (TypeError, ValueError) as e:
                logger.warning(f"年龄转换失败 {cond}: {e}")
                result.append(cond)
        return result
