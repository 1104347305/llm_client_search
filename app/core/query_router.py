"""
查询路由器 - 四层串联漏斗
L1 → L2 → L3 依次执行并累积条件；三层均无条件时转至 L4 (LLM)
"""
from loguru import logger
from app.models.schemas import ParsedQuery, QueryLogic, LogicNode, Condition, Operator
from app.core.level1_rule_engine import Level1RuleEngine
from app.core.level2_enhanced_matcher import Level2EnhancedMatcher
from app.core.level3_semantic_cache import Level3SemanticCache
from app.core.level4_llm_parser import Level4LLMParser
from config.settings import settings
from typing import List, Tuple, Optional
import re


class QueryRouter:
    """查询路由器 - 四层串联漏斗"""

    def __init__(self):
        self.level1 = Level1RuleEngine()
        self.level2 = Level2EnhancedMatcher()
        self.level3 = Level3SemanticCache()
        self.level4 = Level4LLMParser()

        # 逻辑连接词映射
        self.logic_words = {
            '和': QueryLogic.AND,
            '与': QueryLogic.AND,
            '且': QueryLogic.AND,
            '或': QueryLogic.OR,
            '或者': QueryLogic.OR,
            '但': QueryLogic.AND,  # "但" 表示转折，仍是 AND 关系
        }

        logger.info(
            f"Query router initialized | "
            f"L1={'ON' if settings.ENABLE_L1 else 'OFF'} "
            f"L2={'ON' if settings.ENABLE_L2 else 'OFF'} "
            f"L3={'ON' if settings.ENABLE_L3 else 'OFF'} "
            f"L4={'ON' if settings.ENABLE_L4 else 'OFF'}"
        )

    def _detect_logic_operators(self, query: str) -> List[Tuple[int, str, QueryLogic]]:
        """
        检测查询中的逻辑连接词

        Returns:
            List of (position, word, logic_type)
        """
        logic_positions = []
        for word, logic_type in self.logic_words.items():
            pos = 0
            while True:
                pos = query.find(word, pos)
                if pos == -1:
                    break
                logic_positions.append((pos, word, logic_type))
                pos += len(word)

        # 按位置排序
        logic_positions.sort(key=lambda x: x[0])
        return logic_positions

    def _build_logic_tree(self, query: str, conditions: List[Condition]) -> Optional[LogicNode]:
        """
        根据查询中的逻辑词构建逻辑树

        策略：
        1. 如果没有逻辑词，返回 None（使用默认 AND）
        2. 如果只有一种逻辑词（全是 AND 或全是 OR），构建简单逻辑树
        3. 如果有混合逻辑词，按优先级构建嵌套树（AND 优先级高于 OR）
        """
        logic_ops = self._detect_logic_operators(query)

        if not logic_ops:
            # 没有逻辑词，使用默认 AND
            return None

        # 检查是否只有一种逻辑类型
        logic_types = set(op[2] for op in logic_ops)

        if len(logic_types) == 1:
            # 只有一种逻辑类型，构建简单树
            logic_type = logic_types.pop()
            return LogicNode(operator=logic_type, conditions=conditions)

        # 混合逻辑，暂时使用默认 AND（后续可以扩展更复杂的解析）
        logger.warning(f"Mixed logic operators detected in query: {query}, using default AND")
        return None

    async def route_with_peeling(self, query: str) -> ParsedQuery:
        """
        串联流水线路由：
        1. L1 处理原始查询，提取确定性实体
        2. L2 处理原始查询，提取模板条件
        3. L3 对原始查询检索语义缓存
        4. 若 L1+L2+L3 合计条件为空，则转至 L4 (LLM)
        """
        logger.info(f"Routing query: {query}")
        query = query.replace(' ', '')

        all_conditions = []

        # Level 1: 规则引擎 - 提取确定性实体
        l1_conditions = []
        if settings.ENABLE_L1:
            l1_conditions, remaining, _ = await self.level1.extract(query)
            logger.info(f"Level 1 extracted {len(l1_conditions)} conditions")
        else:
            logger.info("Level 1 DISABLED, skipped")

        # Level 2: 增强模板匹配 - 使用原始查询
        l2_conditions = []
        if settings.ENABLE_L2:
            l2_conditions, _, _ = await self.level2.match(query)
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

        # 若存在 CONTAINS+列表条件（enum_gte/lte 展开结果），语义上是 OR（匹配列表中任一值）
        has_enum_list = any(
            cond.operator == Operator.CONTAINS and isinstance(cond.value, list)
            for cond in all_conditions
        )
        query_logic = QueryLogic.OR if has_enum_list else QueryLogic.AND

        return ParsedQuery(
            conditions=all_conditions,
            query_logic=query_logic,
            logic_tree=None,
            confidence=confidence,
            matched_level=matched_level
        )
