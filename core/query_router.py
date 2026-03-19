"""
查询路由器 - 四层串联漏斗
L1 → L2 → L3 依次执行并累积条件；三层均无条件时转至 L4 (LLM)
"""
from loguru import logger
from models.schemas import ParsedQuery, QueryLogic, LogicNode, Condition, Operator
from core.level1_rule_engine import Level1RuleEngine
from core.level2_enhanced_matcher import Level2EnhancedMatcher
from core.level3_semantic_cache import Level3SemanticCache
from core.level4_llm_parser import Level4LLMParser
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

        logger.info(
            f"Query router initialized | "
            f"L1={'ON' if settings.ENABLE_L1 else 'OFF'} "
            f"L2={'ON' if settings.ENABLE_L2 else 'OFF'} "
            f"L3={'ON' if settings.ENABLE_L3 else 'OFF'} "
            f"L4={'ON' if settings.ENABLE_L4 else 'OFF'}"
        )


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
            l1_conditions = await self.level1.extract(query)
            logger.info(f"Level 1 extracted {len(l1_conditions)} conditions")
        else:
            logger.info("Level 1 DISABLED, skipped")

        # Level 2: 增强模板匹配 - 使用原始查询
        l2_conditions = []
        if settings.ENABLE_L2:
            l2_conditions = await self.level2.match(query)
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
