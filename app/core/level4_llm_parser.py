"""
Level 4: LLM 解析器 - 使用 Agno Agent 进行查询解析（兜底方案）

这是四层匹配架构的第四层（兜底层），使用 LLM 分析复杂的自然语言查询。

适用场景：
- 复杂组合查询："45岁以上、已婚、年收入20万以上、且没有购买过养老险的客户"
- 语义推断查询："有小朋友的高收入已婚客户，且保障配置不全"
- 模糊描述查询："高价值潜力客户"
- 时间相关查询："马上要过生日的客户"、"下周过生日的客户"
- 任何 Layer 1/2/3 无法处理的查询

特点：
- 最慢：~500-1000ms 响应时间
- 需要 LLM：消耗 API 配额
- 最灵活：支持任意复杂的自然语言
- 兜底方案：确保所有查询都能被处理
- 支持互联网搜索：可获取实时信息（如当前日期、节假日等）

技术实现：
- 使用 Agno Agent 框架
- 使用 DashScope API（通义千问）
- 使用 output_schema 强制结构化输出
- 支持 100+ 个客户字段
- 集成博查搜索工具获取实时信息
"""
import asyncio
import time
from typing import List
from loguru import logger
from agno.agent import Agent
from agno.models.dashscope import DashScope
from pydantic import BaseModel, Field

from config.settings import settings
from app.models.schemas import ParsedQuery, Condition, QueryLogic, Operator, RangeValue
from app.tools.bocha_search_tool import bocha_web_search
from app.core.field_registry import get_field_registry


# ==================== 输出模型定义 ====================

class QueryAnalysisResult(BaseModel):
    """
    查询分析结果模型

    表示 Agent 分析后的完整结果

    Attributes:
        query_logic: 查询逻辑，"AND" 或 "OR"
            - AND: 所有条件都必须满足（默认）
            - OR: 满足任一条件即可
        conditions: 搜索条件列表
    """
    query_logic: str = Field(default="AND", description="查询逻辑 (AND/OR)")
    conditions: List[dict] = Field(default_factory=list, description="搜索条件列表")


# ==================== Agent 基础指令（静态部分）====================

AGENT_INSTRUCTIONS_BASE = """你是一个专业的客户搜索查询分析专家。你的任务是将用户的自然语言查询转换为结构化的搜索条件。

## 核心约束（最高优先级）

**只能使用下方"参考字段定义"中明确列出的字段名（field）。**
若查询意图找不到匹配的参考字段，该意图对应的条件必须忽略（不输出）。
若参考字段给出了明确的枚举值（enum），必须使用给定的枚举值。
禁止自行推断或编造字段名。

## 操作符说明
- **MATCH**: 精确/模糊匹配
- **CONTAINS**: 数组字段包含某值
- **NOT_CONTAINS**: 数组字段不包含某值（缺口查询）
- **EXISTS / NOT_EXISTS**: 字段有/无数据
- ****: 大于等于 / 小于等于（数值）
- **GTE/LTE/RANGE**: 大于等于/小于等于/区间范围（精确年龄使用RANGE表述，如：45岁--》{"min": 45, "max": 45}）

## 通用规则
- 缺口查询（未配置/没有/未购买/缺少）→ NOT_CONTAINS
- 数值：20万→200000，万=×10000，千=×1000
- **MATCH 仅用于字符串字段；数值字段（age/annual_income等）只用 GTE/LTE/RANGE，精确值用 RANGE {min:x, max:x}**
- 学历层级升序：高中<中专<大学专科<大学本科<硕士研究生<博士研究生<博士后
- 客户温度升序：冷却<低温<中温<高温

## AND 与 OR 的使用规则（极其重要，严禁混淆）

### query_logic: AND（默认，绝大多数情况）
**含义：所有条件同时满足**
- 查询涉及**多个不同字段**的组合筛选时，需所有条件都满足，永远用 AND
- 例：45岁以上，已婚，年收入20万以上 → AND
- 例：没有买过养老险且有小孩 → AND

### query_logic: OR（极少使用，严格限制）
**含义：多个完全不同的独立条件，满足任意一个即可**
- **只有**查询中明确含有"或者"、"任一"等语义，且条件指向**不同字段**时才用 OR
- 例："年龄超过60岁或者年收入超过100万" → OR（两个不同字段）

**同一字段匹配多个候选值时，必须使用 CONTAINS，而非 OR + 多条 MATCH，例如：高温或中温的客户--》{"field": "customer_temperature", "operator": "CONTAINS", "value": ["高温","中温"]}**


## 输出格式（严格 JSON，不加任何其他文字）

{"query_logic": "AND", "conditions": [{"field": "字段名", "operator": "操作符", "value": "值"}]}

## 示例

"45岁以上、已婚、年收入20万以上且没买过养老险"
{"query_logic":"AND","conditions":[{"field":"age","operator":"GTE","value":45},{"field":"marital_status","operator":"MATCH","value":"已婚"},{"field":"annual_income","operator":"GTE","value":200000},{"field":"held_product_category","operator":"NOT_CONTAINS","value":"年金保险"}]}

"本科学历以上的客户"（同一字段多值 → CONTAINS，不是 OR）
{"query_logic":"AND","conditions":[{"field":"education","operator":"CONTAINS","value":["大学本科","硕士研究生","博士研究生","博士后"]}]}

"年龄超过60岁或者年收入超过100万的客户"（不同字段，明确"或者" → OR）
{"query_logic":"OR","conditions":[{"field":"age","operator":"GTE","value":60},{"field":"annual_income","operator":"GTE","value":1000000}]}

"45岁的女性客户"（精确年龄需要使用RANGE表述，min=max=具体年龄）
{"query_logic":"AND","conditions":[{"field":"age","operator":"RANGE","value":{"min": 45, "max": 45}},{"field":"gender","operator":"MATCH","value":"女"}]}

"40岁左右的客户"（年龄左右需要使用RANGE表述）
{"query_logic":"AND","conditions":[{"field":"age","operator":"RANGE","value":{"min": 38, "max": 42}}]}
"""


class Level4LLMParser:
    """LLM 解析器 - 使用 Agno Agent 作为兜底方案（集成 RAG 字段检索）"""

    def __init__(self):
        """初始化 LLM 解析器"""
        # 加载字段注册表（RAG 检索）
        self.field_registry = get_field_registry()

        # 创建查询分析 Agent（使用基础静态指令）
        self.agent = Agent(
            name="QueryAnalyzer",
            instructions=AGENT_INSTRUCTIONS_BASE,
            model=DashScope(
                id=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            ),
            tools=[bocha_web_search],  # 添加博查搜索工具
            output_schema=QueryAnalysisResult,  # 强制结构化输出
            markdown=False,  # 不使用 Markdown 格式
            add_datetime_to_context=True,  # 添加当前时间到上下文
        )
        logger.info(f"Level4 LLM parser initialized with {settings.LLM_MODEL}")

    def _build_rag_message(self, query: str) -> tuple[str, bool]:
        """
        构建带有 RAG 检索字段的消息

        双路检索：
        1. ES BM25 全文检索（top 8）：覆盖语义描述匹配
        2. Trie 枚举精确匹配：覆盖查询中直接出现枚举值的场景
        两路结果按 intent id 去重合并后注入 prompt。

        Returns:
            (message, has_intents): has_intents=False 时调用方应跳过 LLM
        """
        # 路径一：ES BM25 检索
        es_intents = self.field_registry.retrieve(query, top_k=10)

        # 路径二：Trie 枚举精确命中
        trie_intents = self.field_registry.retrieve_by_enum(query)

        # 合并去重（保持 ES 结果顺序优先，Trie 结果追加）
        seen_ids: set = {i.get("id") for i in es_intents}
        merged = list(es_intents)
        for intent in trie_intents:
            if intent.get("id") not in seen_ids:
                merged.append(intent)
                seen_ids.add(intent.get("id"))

        if merged:
            field_section = self.field_registry.format_prompt_section(merged)
            message = f"{field_section}\n\n### 用户查询\n{query}"
            logger.debug(
                f"RAG merged {len(merged)} intents "
                f"(ES={len(es_intents)}, Trie={len(trie_intents)}) for query: {query}"
            )
            return message, True
        else:
            logger.debug(f"RAG found no relevant intents for query: {query}")
            return query, False

    async def parse(self, query: str) -> ParsedQuery:
        """
        解析查询（异步版本）

        Args:
            query: 用户查询

        Returns:
            ParsedQuery
        """
        logger.info(f"Level 4 LLM parsing query: {query}")
        start_time = time.time()

        try:
            # 构建带 RAG 字段上下文的消息
            rag_message, has_intents = self._build_rag_message(query)

            # RAG 未召回任何字段定义 → 无法安全解析，直接返回空
            if not has_intents:
                logger.info(f"Level 4 skipped: no relevant field intents found for query: {query}")
                return ParsedQuery(
                    conditions=[],
                    query_logic=QueryLogic.AND,
                    sort=None,
                    confidence=0.0,
                    matched_level=4
                )

            # 在线程池中运行同步的 agent.run()
            result = await asyncio.to_thread(self.agent.run, rag_message)

            duration = time.time() - start_time

            if result and result.content:
                # 检查返回类型
                if isinstance(result.content, QueryAnalysisResult):
                    conditions = self._convert_conditions(result.content.conditions)
                    query_logic = QueryLogic.AND if result.content.query_logic == "AND" else QueryLogic.OR

                    logger.info(f"Level 4 LLM parsed {len(conditions)} conditions in {duration*1000:.2f}ms")

                    return ParsedQuery(
                        conditions=conditions,
                        query_logic=query_logic,
                        sort=None,
                        confidence=0.8,
                        matched_level=4
                    )
                elif isinstance(result.content, str):
                    # Agent 返回了字符串，尝试解析
                    logger.warning("Agent returned string instead of QueryAnalysisResult")
                    try:
                        import json
                        parsed = json.loads(result.content)
                        if isinstance(parsed, dict):
                            conditions = self._convert_conditions(parsed.get("conditions", []))
                            query_logic_str = parsed.get("query_logic", "AND")
                            query_logic = QueryLogic.AND if query_logic_str == "AND" else QueryLogic.OR

                            return ParsedQuery(
                                conditions=conditions,
                                query_logic=query_logic,
                                sort=None,
                                confidence=0.8,
                                matched_level=4
                            )
                    except Exception as parse_error:
                        logger.error(f"Failed to parse string result: {parse_error}")

            # 返回空结果
            logger.warning("Agent returned empty or invalid result")
            return ParsedQuery(
                conditions=[],
                query_logic=QueryLogic.AND,
                sort=None,
                confidence=0.0,
                matched_level=4
            )

        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"Level 4 LLM parsing failed after {duration*1000:.2f}ms: {e}")
            return ParsedQuery(
                conditions=[],
                query_logic=QueryLogic.AND,
                sort=None,
                confidence=0.0,
                matched_level=4
            )

    def _convert_conditions(self, raw_conditions: List[dict]) -> List[Condition]:
        """
        将原始条件字典转换为 Condition 对象

        Args:
            raw_conditions: 原始条件列表

        Returns:
            Condition 对象列表
        """
        conditions = []
        for cond_data in raw_conditions:
            try:
                # 解析 value
                value = cond_data.get("value")
                if isinstance(value, dict) and "min" in value:
                    value = RangeValue(min=value.get("min"), max=value.get("max"))

                condition = Condition(
                    field=cond_data["field"],
                    operator=Operator(cond_data["operator"]),
                    value=value
                )
                conditions.append(condition)
            except Exception as e:
                logger.warning(f"Failed to convert condition: {cond_data}, error: {e}")

        return conditions
