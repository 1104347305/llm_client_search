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

技术实现：
- 使用 Agno Agent 框架
- 使用 DashScope API（通义千问）
- 使用 output_schema 强制结构化输出
- 支持 100+ 个客户字段
"""
import asyncio
import json
import re
import time
import warnings
from typing import List, Any, Dict
from datetime import datetime
from zoneinfo import ZoneInfo
from loguru import logger
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from config.settings import settings
from models.schemas import ParsedQuery, Condition, QueryLogic, Operator, RangeValue
from core.field_registry import get_field_registry
from core.level2_enhanced_matcher import Level2EnhancedMatcher
from core.time_range_resolver import resolve_dynamic_date_placeholder
from utils.sensitive_masking import mask_for_log

# agno 依赖中的部分 Pydantic 模型使用了 model_id/model_provider 字段，
# 在 Pydantic v2 下会触发已知的 protected_namespaces 警告。该警告来自三方库，
# 不影响当前业务逻辑，这里仅静默这两条固定噪音。
warnings.filterwarnings(
    "ignore",
    message=r'Field "model_id" has conflict with protected namespace "model_"\.',
    category=UserWarning,
    module=r"pydantic\._internal\._fields",
)
warnings.filterwarnings(
    "ignore",
    message=r'Field "model_provider" has conflict with protected namespace "model_"\.',
    category=UserWarning,
    module=r"pydantic\._internal\._fields",
)


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

class Level4LLMParser:
    """LLM 解析器 - 使用原生异步 OpenAI 兼容接口作为兜底方案（集成 RAG 字段检索）"""

    _RAG_MULTI_INTENT_FIELDS = {"planAbbrNames"}
    _RAG_SOURCE_SCORES = {
        "l2": 0.95,
        "trie": 0.90,
        "es": 0.85,
    }

    def __init__(self):
        """初始化 LLM 解析器"""
        from agno.agent import Agent
        from agno.models.dashscope import DashScope

        # 加载字段注册表（RAG 检索）
        self.field_registry = get_field_registry()
        self.level2_recall = Level2EnhancedMatcher() if settings.ENABLE_L4_RAG_L2 else None

        # 创建查询分析 Agent（使用基础静态指令）
        self.agent = Agent(
            name="QueryAnalyzer",
            instructions=settings.AGENT_INSTRUCTIONS_BASE,
            model=DashScope(
                id=settings.LLM_MODEL,
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            ),
            tools=[],  # 添加博查搜索工具
            output_schema=QueryAnalysisResult,  # 强制结构化输出
            markdown=False,  # 不使用 Markdown 格式
            add_datetime_to_context=True,  # 添加当前时间到上下文
        )

        # 原生异步客户端，兼容 DashScope OpenAI 接口
        self.client = AsyncOpenAI(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
        )
        self.model = settings.LLM_MODEL
        self.system_prompt = settings.AGENT_INSTRUCTIONS_BASE
        logger.info(f"Level4 LLM parser initialized with {settings.LLM_MODEL} (native async)")

    async def _build_rag_message(self, query: str) -> tuple[str, bool]:
        """
        构建带有 RAG 检索字段的消息

        三路检索：
        1. ES BM25 全文检索（top 8）：覆盖语义描述匹配
        2. Trie 枚举精确匹配：覆盖查询中直接出现枚举值的场景
        3. L2 规则片段召回：基于增强规则 partial search 召回相关字段
        三路结果按 field 聚合后注入 prompt，避免同字段多条 intent 挤占 top_k。

        Returns:
            (message, has_intents): has_intents=False 时调用方应跳过 LLM
        """
        top_k = settings.L4_RAG_TOP_K

        async def _retrieve_es() -> List[Dict[str, Any]]:
            if not settings.ENABLE_L4_RAG_ES:
                return []
            return await asyncio.to_thread(self.field_registry.retrieve, query, top_k)

        async def _retrieve_trie() -> List[Dict[str, Any]]:
            if not settings.ENABLE_L4_RAG_TRIE:
                return []
            return await asyncio.to_thread(self.field_registry.retrieve_by_enum, query)

        async def _retrieve_l2() -> List[Dict[str, Any]]:
            if not settings.ENABLE_L4_RAG_L2 or self.level2_recall is None:
                return []
            if hasattr(self.level2_recall, "recall_candidates"):
                recalled = await asyncio.to_thread(self.level2_recall.recall_candidates, query, top_k)
                pairs = [(item["field"], item["operator"]) for item in recalled]
                if hasattr(self.field_registry, "retrieve_by_field_operator_pairs"):
                    return await asyncio.to_thread(self.field_registry.retrieve_by_field_operator_pairs, pairs)
                fields = [item["field"] for item in recalled]
                return await asyncio.to_thread(self.field_registry.retrieve_by_fields, fields)
            recalled = await asyncio.to_thread(self.level2_recall.recall_fields, query, top_k)
            fields = [item["field"] for item in recalled]
            return await asyncio.to_thread(self.field_registry.retrieve_by_fields, fields)

        es_intents, trie_intents, l2_intents = await asyncio.gather(
            _retrieve_es(),
            _retrieve_trie(),
            _retrieve_l2(),
        )

        merged = self._merge_rag_intents_by_field(
            trie_intents=trie_intents,
            l2_intents=l2_intents,
            es_intents=es_intents,
            top_k=top_k,
        )

        if merged:
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            weekday_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            current_time = now.strftime("%Y-%m-%d %H:%M:%S")
            current_weekday = weekday_names[now.weekday()]
            field_section = self.field_registry.format_prompt_section(merged, query=query)
            message = (
                f"### 当前时间\n{current_time} (Asia/Shanghai)\n"
                f"### 今天星期\n{current_weekday}\n\n"
                f"{field_section}\n\n### 用户查询\n{query}"
            )
            logger.debug(
                f"RAG merged {len(merged)} fields "
                f"(ES={'ON' if settings.ENABLE_L4_RAG_ES else 'OFF'}:{len(es_intents)}, "
                f"Trie={'ON' if settings.ENABLE_L4_RAG_TRIE else 'OFF'}:{len(trie_intents)}, "
                f"L2={'ON' if settings.ENABLE_L4_RAG_L2 else 'OFF'}:{len(l2_intents)}, "
                f"TOP_K={top_k}) for query: {mask_for_log(query)}"
            )
            return message, True
        else:
            logger.debug(f"RAG found no relevant intents for query: {mask_for_log(query)}")
            return query, False

    @staticmethod
    def _merge_rag_intents_by_field(
        trie_intents: List[Dict[str, Any]],
        l2_intents: List[Dict[str, Any]],
        es_intents: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        """按字段+操作符聚合 RAG 结果，融合多路召回分值并优先保留多路共识知识。"""
        merged_by_key: Dict[str, Dict[str, Any]] = {}
        source_order = {"l2": 0, "trie": 1, "es": 2}
        sequence = 0
        l2_ops_by_field: Dict[str, set[str]] = {}

        def _dedupe_key(intent: Dict[str, Any]) -> str:
            field = str(intent.get("field", "")).strip()
            operator = str(intent.get("operator", "")).strip() or "_"
            if field in Level4LLMParser._RAG_MULTI_INTENT_FIELDS:
                intent_id = str(intent.get("id", "")).strip() or "_"
                return f"{field}::{operator}::{intent_id}"
            return f"{field}::{operator}"

        for intent in l2_intents:
            field = str(intent.get("field", "")).strip()
            operator = str(intent.get("operator", "")).strip() or "_"
            if not field:
                continue
            l2_ops_by_field.setdefault(field, set()).add(operator)

        def _consume(intents: List[Dict[str, Any]], source: str) -> None:
            nonlocal sequence
            for intent in intents:
                field = str(intent.get("field", "")).strip()
                operator = str(intent.get("operator", "")).strip() or "_"
                key = _dedupe_key(intent)
                if not field:
                    continue
                if source != "l2" and field in l2_ops_by_field and operator not in l2_ops_by_field[field]:
                    continue
                score = Level4LLMParser._RAG_SOURCE_SCORES[source]
                rank = sequence * 10 + source_order[source]
                sequence += 1
                existing = merged_by_key.get(key)
                if existing is None:
                    merged_by_key[key] = {
                        "score": score,
                        "rank": rank,
                        "intent": intent,
                        "sources": {source},
                        "best_single_score": score,
                    }
                    continue

                previous_best_single = existing["best_single_score"]
                if source not in existing["sources"]:
                    existing["score"] += score
                    existing["sources"].add(source)

                # 展示内容优先保留单路质量更高的意图；同分时保留更早出现的。
                if score > previous_best_single or (score == previous_best_single and rank < existing["rank"]):
                    existing["intent"] = intent
                    existing["rank"] = rank
                    existing["best_single_score"] = score

        _consume(l2_intents, "l2")
        _consume(trie_intents, "trie")
        _consume(es_intents, "es")

        ranked = sorted(
            merged_by_key.values(),
            key=lambda item: (-item["score"], -len(item["sources"]), item["rank"]),
        )
        logger.debug(
            "RAG fused ranking: {}",
            [
                {
                    "id": str(item["intent"].get("id", "")).strip(),
                    "field": str(item["intent"].get("field", "")).strip(),
                    "operator": str(item["intent"].get("operator", "")).strip() or "_",
                    "score": round(float(item["score"]), 4),
                    "sources": sorted(item["sources"]),
                }
                for item in ranked[:top_k]
            ],
        )
        return [item["intent"] for item in ranked[:top_k]]

    async def agent_parse(self, query: str) -> ParsedQuery:
        """
        解析查询（异步版本）

        Args:
            query: 用户查询

        Returns:
            ParsedQuery
        """
        logger.info(f"Level 4 LLM parsing query: {mask_for_log(query)}")
        start_time = time.time()

        try:
            # 构建带 RAG 字段上下文的消息
            rag_message, has_intents = await self._build_rag_message(query)

            # RAG 未召回任何字段定义 → 无法安全解析，直接返回空
            if not has_intents:
                logger.info(f"Level 4 skipped: no relevant field intents found for query: {mask_for_log(query)}")
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

    async def parse(self, query: str) -> ParsedQuery:
        """
        解析查询（异步版本）

        Args:
            query: 用户查询

        Returns:
            ParsedQuery
        """
        logger.info(f"Level 4 LLM parsing query: {mask_for_log(query)}")
        start_time = time.time()

        try:
            # 构建带 RAG 字段上下文的消息
            rag_message, has_intents = await self._build_rag_message(query)

            # RAG 未召回任何字段定义 → 无法安全解析，直接返回空
            if not has_intents:
                logger.info(f"Level 4 skipped: no relevant field intents found for query: {mask_for_log(query)}")
                return ParsedQuery(
                    conditions=[],
                    query_logic=QueryLogic.AND,
                    sort=None,
                    confidence=0.0,
                    matched_level=4,
                    prompt=rag_message
                )

            # 直接调用异步 OpenAI 兼容接口
            # enable_thinking=False 关闭 qwen3 系列 thinking 模式，大幅降低延迟
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": rag_message},
                ],
                temperature=float(getattr(settings, 'LLM_TEMPERATURE', 0.01)),
                max_tokens=int(getattr(settings, 'LLM_MAX_TOKENS', 2000)),
                extra_body={"enable_thinking": False}
            )

            duration = time.time() - start_time
            msg = response.choices[0].message
            raw_content = msg.content or ""

            # qwen-thinking 系列模型正文可能在 reasoning_content 之后，content 为空时尝试 tool_calls
            if not raw_content and hasattr(msg, 'tool_calls') and msg.tool_calls:
                raw_content = msg.tool_calls[0].function.arguments or ""

            # 记录 finish_reason 帮助诊断
            finish_reason = response.choices[0].finish_reason
            logger.debug(
                f"LLM response in {duration*1000:.2f}ms | finish={finish_reason} | "
                f"content_len={len(raw_content)} | preview={raw_content[:200]}"
            )
            if not raw_content:
                logger.warning(f"LLM returned empty content, finish_reason={finish_reason}")

            # 从文本中提取 JSON（兼容 thinking 模型输出 <think>...</think> 前缀）
            json_str = raw_content
            # 尝试找到第一个 { 开始的 JSON 块
            m = re.search(r'\{.*\}', raw_content, re.DOTALL)
            if m:
                json_str = m.group(0)

            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    conditions = self._convert_conditions(parsed.get("conditions", []))
                    query_logic_str = parsed.get("query_logic", "AND")
                    query_logic = QueryLogic.AND if query_logic_str == "AND" else QueryLogic.OR
                    logger.info(f"Level 4 LLM parsed {len(conditions)} conditions in {duration*1000:.2f}ms")
                    return ParsedQuery(
                        conditions=conditions,
                        query_logic=query_logic,
                        sort=None,
                        confidence=0.8,
                        matched_level=4,
                        prompt=rag_message
                    )
            except Exception as parse_error:
                logger.error(
                    f"Failed to parse LLM JSON response: {parse_error}, raw: {mask_for_log(json_str[:500])}"
                )

            # 返回空结果
            logger.warning("Agent returned empty or invalid result")
            return ParsedQuery(
                conditions=[],
                query_logic=QueryLogic.AND,
                sort=None,
                confidence=0.0,
                matched_level=4,
                prompt=rag_message
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
                field = cond_data["field"]

                # 解析 value
                value = cond_data.get("value")
                if isinstance(value, dict) and "min" in value:
                    value = RangeValue(
                        min=self._normalize_field_value(field, self._resolve_dynamic_date_placeholder(value.get("min"))),
                        max=self._normalize_field_value(field, self._resolve_dynamic_date_placeholder(value.get("max"))),
                    )
                else:
                    value = self._resolve_dynamic_date_placeholder(value)
                    value = self._normalize_field_value(field, value)

                condition = Condition(
                    field=field,
                    operator=Operator(cond_data["operator"]),
                    value=value
                )
                conditions.append(condition)
            except Exception as e:
                logger.warning(f"Failed to convert condition: {cond_data}, error: {e}")

        return conditions

    def _resolve_dynamic_date_placeholder(self, value):
        """将 LLM 可能输出的动态日期占位符展开为具体时间。"""
        resolved = resolve_dynamic_date_placeholder(value)
        if resolved != value:
            logger.debug(f"Resolved dynamic date placeholder '{value}' -> '{resolved}'")
        return resolved

    def _normalize_field_value(self, field: str, value: Any) -> Any:
        """字段级格式归一。"""
        if field == "birthdayMd" and isinstance(value, str):
            normalized = self._normalize_birthday_md(value)
            if normalized is not None:
                return normalized
        return self.field_registry.normalize_field_value(field, value)

    @staticmethod
    def _normalize_birthday_md(value: str) -> Any:
        text = value.strip()
        if not text:
            return value

        # 兼容 YYYY-MM-DD / YYYY-MM-DD HH:mm:ss
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.strftime("%m-%d")
            except ValueError:
                continue

        # 已经是 MM-dd 时保持原样
        if re.fullmatch(r"\d{2}-\d{2}", text):
            return text

        return value
