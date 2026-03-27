"""
查询路由器 - 四层串联漏斗
L1 → L2 → L3 依次执行并累积条件；三层均无条件时转至 L4 (LLM)
"""
from loguru import logger
from models.schemas import ParsedQuery, QueryLogic, LogicNode, Condition, Operator, RangeValue
from core.level1_rule_engine import Level1RuleEngine
from core.level2_enhanced_matcher import Level2EnhancedMatcher
from core.level3_semantic_cache import Level3SemanticCache
from core.level4_llm_parser import Level4LLMParser
from core.field_registry import get_field_registry
from config.settings import settings
from typing import List, Tuple, Optional, Set, Dict
from pathlib import Path
import re
import yaml


class QueryRouter:
    """查询路由器 - 四层串联漏斗"""

    def __init__(self):
        self.level1 = Level1RuleEngine()
        self.level2 = Level2EnhancedMatcher()
        self.level3 = Level3SemanticCache()
        self.level4 = Level4LLMParser()
        self.field_registry = get_field_registry()

        # 加载已知字段和枚举值，用于 L4 输出后处理校验
        self._valid_fields: Set[str] = set()
        self._enum_values: Dict[str, List[str]] = {}
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
        for f in sorted(enums_dir.glob('*.yaml')):
            if f.resolve() == value_mappings_path:
                continue
            raw = yaml.safe_load(f.read_text(encoding='utf-8')) or {}
            for field, entry in raw.items():
                vals = entry.get('values', []) if isinstance(entry, dict) else list(entry)
                if vals:
                    self._enum_values[field] = [str(v) for v in vals]


    async def route_with_peeling(self, query: str) -> ParsedQuery:
        """
        串联流水线路由：
        1. L1 处理原始查询，提取确定性实体
        2. L2 处理原始查询，提取模板条件
        3. L3 对原始查询检索语义缓存
        4. 若 L1+L2+L3 合计条件为空，则转至 L4 (LLM)
        """
        original_query = query
        logger.info(f"Routing query: {original_query}")
        query = query.replace(' ', '')
        normalized_query = self.field_registry.normalize_query(query)
        if normalized_query != query:
            logger.info(f"Query normalized: '{query}' -> '{normalized_query}'")
        query = normalized_query
        self._last_rewritten_query = query
        self._last_matched_patterns = []

        all_conditions = []

        # Level 1: 规则引擎 - 提取确定性实体
        l1_conditions = []
        if settings.ENABLE_L1:
            l1_conditions = await self.level1.extract(query)
            self._last_matched_patterns = list(getattr(self.level1, "_last_matched_patterns", []))
            logger.info(f"Level 1 extracted {len(l1_conditions)} conditions")
        else:
            logger.info("Level 1 DISABLED, skipped")

        # Level 2: 增强模板匹配 - 使用原始查询
        l2_conditions = []
        if settings.ENABLE_L2:
            l2_conditions = await self.level2.match(query)
            self._last_matched_patterns.extend(list(getattr(self.level2, "_last_matched_patterns", [])))
            logger.info(f"Level 2 matched {len(l2_conditions)} conditions")
        else:
            logger.info("Level 2 DISABLED, skipped")

        # 合并 L1 和 L2 条件：L2 优先，字段级别覆盖
        # L1 的 name 字段（Jieba 分词）误判率高；只要 L2 有任何匹配，就以 L2 为准，丢弃 L1 的 name
        l1_low_confidence_fields = {'name'}

        # L2 精确嵌套字段 → 覆盖 L1 通用字段映射
        # 当 L2 命中更精确的嵌套字段时，丢弃 L1 对应的通用字段（如家庭成员手机 > 客户手机）
        l2_supersedes_l1: dict[str, str] = {
            "family_members.mobile": "mobile_phone",
        }

        # 收集 L2 匹配的所有字段
        l2_fields = {cond.field for cond in l2_conditions}

        # 计算被 L2 精确字段隐式覆盖的 L1 字段
        l1_superseded = {
            l1_field for l2_field, l1_field in l2_supersedes_l1.items()
            if l2_field in l2_fields
        }

        # 过滤 L1 条件：L2 有匹配时移除 name；始终移除被 L2 覆盖的同字段或被隐式覆盖的字段
        if l2_conditions:
            l1_conditions_filtered = [
                cond for cond in l1_conditions
                if cond.field not in l2_fields
                and cond.field not in l1_low_confidence_fields
                and cond.field not in l1_superseded
            ]
            logger.info(f"L2 matched, removing L1 low-confidence 'name' field")
        else:
            l1_conditions_filtered = [cond for cond in l1_conditions if cond.field not in l2_fields]

        # 先添加 L1 未被覆盖的条件，再添加 L2 的条件
        all_conditions.extend(l1_conditions_filtered)
        all_conditions.extend(l2_conditions)

        logger.info(f"After L2 override: kept {len(l1_conditions_filtered)} from L1, added {len(l2_conditions)} from L2")

        # Level 3: 语义缓存 - 始终对原始查询检索
        cached = None
        if settings.ENABLE_L3:
            cached = await self.level3.get(query)
            if cached:
                all_conditions.extend(cached.conditions)
                logger.info(f"Level 3 cache hit, added {len(cached.conditions)} conditions")
        else:
            logger.info("Level 3 DISABLED, skipped")

        # L1+L2+L3 均无条件 → Level 4 (LLM)
        if not all_conditions:
            if settings.ENABLE_L4:
                logger.info("No conditions from L1+L2+L3, falling back to Level 4 (LLM)")
                parsed = await self.level4.parse(query)
                # parsed = await self.level4.agent_parse(query)
                # parsed.conditions = self._convert_age_to_birthday(parsed.conditions)
                parsed.conditions = self._validate_conditions(parsed.conditions)
                parsed.rewritten_query = self._last_rewritten_query
                parsed.matched_patterns = self._last_matched_patterns
                if settings.ENABLE_L3:
                    await self.level3.set(query, parsed)
                return parsed
            else:
                logger.warning("No conditions found and Level 4 DISABLED — returning empty result")
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

        # 后处理：校验所有条件（字段名+枚举值），有非法条件则返回空
        all_conditions = self._validate_conditions(all_conditions)

        return ParsedQuery(
            conditions=all_conditions,
            # 外层 query_logic 仅表示多个 condition 之间的关系。
            # 单个 condition 内部的 CONTAINS + list 由接口按 IN/OR 语义解释，
            # 不能提升为外层 OR，否则会错误放宽多个条件之间的约束。
            query_logic=QueryLogic.AND,
            logic_tree=None,
            confidence=confidence,
            matched_level=matched_level,
            rewritten_query=self._last_rewritten_query,
            matched_patterns=self._last_matched_patterns,
        )

    def _validate_conditions(self, conditions: List[Condition]) -> List[Condition]:
        """
        校验所有层级输出的条件。若存在任何非法条件，返回空列表（避免条件缺失导致错误结果）。
        校验规则：
        - 字段名不在 field_definitions.yaml 中 → 整体返回空
        - 字段有枚举约束且值（字符串）不在枚举中 → 整体返回空
        """
        if not self._valid_fields:
            return conditions  # 未加载校验数据，跳过校验

        for cond in conditions:
            # 1. 校验字段名
            if cond.field not in self._valid_fields:
                logger.warning(
                    f"条件校验失败：非法字段 '{cond.field}'（值={cond.value!r}），返回空条件"
                )
                return []

            if cond.operator in {Operator.EXISTS, Operator.NOT_EXISTS}:
                continue

            # 2. 校验枚举值
            enum_vals = self._enum_values.get(cond.field)
            if enum_vals and isinstance(cond.value, str):
                if cond.value not in enum_vals:
                    logger.warning(
                        f"条件校验失败：字段 '{cond.field}' 的值非法，"
                        f"错误值={cond.value!r}，合法枚举={enum_vals!r}，返回空条件"
                    )
                    return []
            elif enum_vals and isinstance(cond.value, list):
                invalid_values = [value for value in cond.value if isinstance(value, str) and value not in enum_vals]
                if invalid_values:
                    logger.warning(
                        f"条件校验失败：字段 '{cond.field}' 的列表值存在非法项，"
                        f"错误值={invalid_values!r}，原始值={cond.value!r}，合法枚举={enum_vals!r}，返回空条件"
                    )
                    return []

        return conditions

    def _convert_age_to_birthday(self, conditions: List[Condition]) -> List[Condition]:
        """
        后处理：将年龄条件转换为出生日期范围条件。
        clientAge       → clientBirthday
        familyClientAge → familyClientBirthday

        逻辑（当前年份 year）：
        - GTE N  → birthday LTE {year-N}-12-31 00:00:00（年龄越大，出生越早）
        - LTE N  → birthday GTE {year-N}-01-01 00:00:00
        - RANGE [min_age, max_age] → birthday RANGE [{year-max_age}-01-01, {year-min_age}-12-31]
        """
        from datetime import date
        year = date.today().year

        age_field_map = {
            'clientAge': 'clientBirthday',
            'familyClientAge': 'familyClientBirthday',
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
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.RANGE,
                        value=RangeValue(
                            min=f"{year - max_age}-01-01 00:00:00",
                            max=f"{year - min_age}-12-31 00:00:00",
                        ),
                    )
                elif cond.operator == Operator.GTE:
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.LTE,
                        value=f"{year - int(v)}-12-31 00:00:00",
                    )
                elif cond.operator == Operator.LTE:
                    new_cond = Condition(
                        field=target_field,
                        operator=Operator.GTE,
                        value=f"{year - int(v)}-01-01 00:00:00",
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
