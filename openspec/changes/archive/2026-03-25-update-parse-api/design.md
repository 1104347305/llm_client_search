## Context

当前 `POST /api/v1/parse` 路由在 `routes.py` 中直接接受 `ParseRequest {query: str}`，调用 `QueryRouter.route_with_peeling()` 后将 `ParsedQuery` 字段手动拼成匿名字典返回。上游 AskBob 平台要求对齐标准 Bot 接入协议，需要重构入参和出参格式，同时保持内部解析链路（L1/L2/L3/L4）不变。

## Goals / Non-Goals

**Goals:**
- 新增 `ParseApiRequest` Pydantic 模型，对齐 AskBob 协议入参字段。
- 新增 `ParseApiResponse` Pydantic 模型，实现 `{code, msg, data}` 标准包装。
- 路由层完成新旧字段映射：`user_text` → 内部 `query`，`user_id` → 日志 `agent_id`，`trace_id` 透传至响应。
- `robot_text` 由解析意图摘要生成（条件数量 + query_logic 简述）。
- 异常响应统一返回 `{code: 500, msg: <错误信息>, data: null}`，HTTP 状态码保持 200（符合 Bot 协议惯例）。

**Non-Goals:**
- 不修改 `QueryRouter` 及 L1/L2/L3/L4 解析逻辑。
- 不新增 `/api/v2/parse` 端点，直接替换现有路由。
- 不处理 `extra_input_params` 中的结构化参数（当前忽略）。
- 不修改 `/api/v1/search/natural` 等其他接口。
## Decisions

1. **新增独立请求/响应模型，不复用 `ParseRequest` / `ParsedQuery`**
   理由：AskBob 协议字段与内部模型语义不同，强行复用会导致 schema 污染。独立模型使接口层与解析层边界清晰。
   备选：直接在 `ParseRequest` 上加字段。否决原因：破坏单一职责，影响其他调用方。

2. **异常响应使用 HTTP 200 + `code=500`，而非 HTTP 500**
   理由：AskBob Bot 协议要求响应始终为 200，通过 `code` 字段区分成功/失败。
   备选：沿用 HTTP 500。否决原因：不符合 Bot 协议，上游无法正常处理。

3. **`robot_text` 由路由层根据解析结果生成，不依赖 LLM**
   理由：避免额外 LLM 调用带来的延迟和不确定性。简单规则生成足够：有条件时返回「已解析 N 个查询条件」，无条件时返回「未能解析查询条件」。
   备选：LLM 生成摘要。否决原因：性能开销不可控。

4. **`trace_id` 由调用方传入并在响应 `data` 层原样透传**
   理由：调用方需用 `trace_id` 关联上下游日志，服务端不生成、不修改。

## Risks / Trade-offs

- [BREAKING 变更，旧调用方立即失效] → 需与所有调用方（含 AskBob）约定切换时间，不提供兼容层。
- [robot_text 生成规则过于简单] → 当前仅满足基本需求，后续可扩展为更丰富的意图描述，不影响响应结构。
- [extra_input_params 当前被忽略] → 若后续需要从中提取结构化参数，需在路由层单独处理，不影响本次变更范围。
- [日志层 agent_id 取值变更] → `request_logger.log()` 调用中 `agent_id` 参数需从 `request.user_id` 获取，需同步修改，否则日志字段为空。

## 字段映射关系

```
入参映射：
  request.user_text        → QueryRouter 内部 query
  request.user_id          → request_logger agent_id
  request.trace_id         → response.data.trace_id
  request.session_id       → 当前忽略（可扩展）
  request.extra_input_params → 当前忽略（可扩展）

出参映射（extra_output_params）：
  parsed.conditions        → conditions
  parsed.query_logic       → query_logic
  parsed.matched_level     → matched_level
  parsed.rewritten_query   → rewritten_query
  parsed.matched_patterns  → matched_patterns（含 L4 prompt）
  request.user_text        → query（原始问题回传）
  parsed.elapsed_times               → last_times（注意字段名拼写）
```

