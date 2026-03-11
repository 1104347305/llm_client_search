"""
AgentOS 入口 - 将客户搜索 Agent 接入 os.agno.com 控制台

启动方式：
    python agent_os_app.py

访问控制台：
    打开 https://os.agno.com，添加端点 http://localhost:7777

环境变量：
    AGNO_API_KEY   - 从 https://www.agno.com 注册后获取（连接控制台需要）
    OS_SECURITY_KEY - 可选，给 OS 接口加 Bearer Token 保护
"""
import asyncio
from agno.agent import Agent
from agno.models.dashscope import DashScope
from agno.os import AgentOS
from agno.tools import tool

from config.settings import settings
from app.core.query_router import QueryRouter
from app.services.search_api_client import SearchAPIClient


# ==================== 工具定义 ====================

router = QueryRouter()
api_client = SearchAPIClient()


# 默认展示字段（精简）
_DEFAULT_DISPLAY_FIELDS = [
    "name", "mobile_phone", "age", "gender",
    "marital_status", "life_insurance_vip", "customer_value",
    "customer_temperature", "operation_stage",
]


def _format_customer(customer: dict, display_fields: list) -> str:
    """将客户 dict 格式化为单行文字，只取 display_fields 中的字段"""
    parts = []
    for field in display_fields:
        val = customer.get(field)
        if val is not None and val != "" and val != "-":
            parts.append(f"{field}:{val}")
    return "  ".join(parts) if parts else "(无数据)"


@tool
async def search_customers(
    query: str,
    agent_id: str = "A000000",
    page: int = 1,
    size: int = 20,
    display_fields: str = "",
) -> str:
    """
    根据自然语言描述搜索客户

    Args:
        query: 自然语言查询，如"45岁以上已婚的高收入客户"
        agent_id: 代理人号，默认 A000000
        page: 页码，默认 1
        size: 每页数量，默认 20（最多100）
        display_fields: 逗号分隔的展示字段，留空使用默认字段
                       默认字段：name,mobile_phone,age,gender,marital_status,
                                life_insurance_vip,customer_value,customer_temperature

    Returns:
        搜索结果摘要（仅包含指定字段，不返回客户全部字段）
    """
    try:
        parsed = await router.route_with_peeling(query)

        if not parsed.conditions:
            return "未能从查询中提取有效条件，请尝试更具体的描述。"

        from app.models.schemas import SearchRequest, RequestHeader
        request = SearchRequest(
            header=RequestHeader(agent_id=agent_id, page=page, size=min(size, 100)),
            query_logic=parsed.query_logic,
            conditions=parsed.conditions,
        )

        result = await api_client.search(request)
        data = result.get("data", {})
        total = data.get("total", 0)
        customers = data.get("list", [])

        from app.db.request_logger import get_request_logger
        await get_request_logger().log(
            agent_id=agent_id,
            query=query,
            request_payload=request.model_dump(),
            response_data=data,
            matched_level=parsed.matched_level,
            confidence=parsed.confidence,
        )

        # 从查询条件中提取展示用字段名：
        # - 顶层字段（policies.xxx → policies）用于嵌套对象
        # - 平铺字段直接使用原始字段名（age、mobile_phone 等）
        condition_fields = []
        for c in parsed.conditions:
            top_field = c.field.split(".")[0]
            if top_field not in condition_fields:
                condition_fields.append(top_field)

        # 确定基础展示字段：用户指定优先，否则使用默认字段
        if display_fields:
            fields = [f.strip() for f in display_fields.split(",") if f.strip()]
        else:
            fields = list(_DEFAULT_DISPLAY_FIELDS)

        # 条件字段强制合并（无论用户是否指定了 display_fields，条件字段必须可见）
        for f in condition_fields:
            if f not in fields:
                fields.append(f)

        # 格式化查询条件块（置于结果最前）
        cond_rows = []
        for c in parsed.conditions:
            val = c.value
            if hasattr(val, "min"):
                val = f"{val.min}~{val.max}"
            cond_rows.append(f"| `{c.field}` | {c.operator.value} | {val} |")

        logic_label = parsed.query_logic if parsed.query_logic else "AND"
        lines = [
            f"**查询条件** · Level {parsed.matched_level} · 置信度 {parsed.confidence:.0%} · 逻辑 `{logic_label}`",
            "",
            "| 字段 | 运算符 | 值 |",
            "| --- | --- | --- |",
            *cond_rows,
            "",
            f"共找到 **{total}** 位客户，展示第 {page} 页（{len(customers)} 条）：",
        ]

        # 格式化客户列表（仅指定字段）
        for i, customer in enumerate(customers, 1):
            lines.append(f"{i}. {_format_customer(customer, fields)}")

        return "\n".join(lines)

    except Exception as e:
        return f"搜索出错：{e}"


@tool
async def retrieve_fields(query: str, top_k: int = 6) -> str:
    """
    根据查询召回相关字段定义（用于了解搜索条件的字段映射）

    Args:
        query: 自然语言查询
        top_k: 返回字段意图数量

    Returns:
        相关字段定义说明
    """
    from app.core.field_registry import get_field_registry
    registry = get_field_registry()
    intents = registry.retrieve(query, top_k=top_k)
    return registry.format_prompt_section(intents) or "未找到相关字段定义"


# ==================== Agent 定义 ====================

customer_search_agent = Agent(
    name="客户搜索助手",
    description="帮助保险代理人用自然语言搜索客户，支持多维度条件组合查询",
    instructions="""你是一个专业的客户搜索助手，服务于保险代理人。

你的能力：
1. 接收自然语言查询（如"45岁以上、已婚、未配置重疾险的客户"）
2. 调用 search_customers 工具执行搜索并返回结果
3. 调用 retrieve_fields 工具查看某个查询涉及哪些字段

使用规则：
- 收到搜索类问题时，直接调用 search_customers，不要让用户等待
- 如果用户想了解某个查询会用到哪些字段，使用 retrieve_fields
- 搜索结果以清晰的表格或列表展示
- 如果搜索结果为空，建议用户放宽条件

支持的查询示例：
- "本月生日的客户"
- "45岁以上已婚年收入20万以上的客户"
- "子女在读初中或高中的客户"
- "未配置重疾险的高净值客户"
- "保单号P644037的客户"
- "寿险VIP黄金V1级别的客户"
""",
    model=DashScope(
        id=settings.LLM_MODEL,
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
    ),
    tools=[search_customers, retrieve_fields],
    markdown=True,
    add_datetime_to_context=True,
)


# ==================== AgentOS ====================

agent_os = AgentOS(
    name="客户搜索系统",
    description="保险代理人客户智能搜索平台",
    agents=[customer_search_agent],
    tracing=True,
)

app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(
        app="agent_os_app:app",
        host="localhost",
        port=7777,
        reload=True,
    )
