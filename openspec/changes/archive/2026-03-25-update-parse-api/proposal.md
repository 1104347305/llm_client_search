## Why

当前 `/api/v1/parse` 接口采用简单的 `{query, agent_id}` 入参和扁平 JSON 出参，缺乏统一的平台接入规范（来源标识、会话追踪、请求 trace）。上游调用方（如 AskBob 平台）要求接口对齐标准 Bot 接入协议，包含 `source`、`session_id`、`trace_id`、`user_action`、`action_scenario` 等字段，以及统一的 `{code, msg, data}` 响应包装结构。现有接口无法满足该协议，需整体重构请求/响应格式。

## What Changes

- **BREAKING** 入参字段全面重命名并扩展：`query` → `user_text`，`agent_id` → `user_id`，新增 `source`、`session_id`、`trace_id`、`ts`、`user_action`、`action_scenario`、`extra_input_params`。
- **BREAKING** 响应结构由扁平字段改为标准包装格式：`{ code, msg, data: { robot_text, end_flag, extra_output_params, trace_id } }`，原有解析结果字段移入 `extra_output_params`。
- 成功响应固定返回 `code=0`、`msg="操作成功"`；异常响应返回非零 `code` 及错误描述。
- `robot_text` 字段返回解析意图的自然语言摘要，`end_flag` 固定为 `1`（表示单轮结束）。
- `trace_id` 在响应 `data` 层原样透传，方便调用方关联请求与响应。
- 原有 `extra_input_params` 扩展字段支持未来结构化参数透传，当前解析层忽略该字段。

## Capabilities

### New Capabilities
- `parse-api-v2`: 重构 `/api/v1/parse` 的请求/响应格式，对齐 AskBob 平台 Bot 接入协议，包含标准入参、统一响应包装和 trace 透传。

### Modified Capabilities

无（当前 `openspec/specs/` 中无已有规格文件）

## Impact

- **接口**：`POST /api/v1/parse` 入参和出参全部变更，为 BREAKING 变更，需与调用方同步切换。
- **代码**：`models/schemas.py`（新增请求/响应 Pydantic 模型）、`routes.py`（路由层重写响应组装逻辑）。
- **日志**：`db/request_logger.py` 中 `agent_id` 取值字段需从 `user_id` 获取。
- **测试**：现有 parse 路由测试需全部更新以匹配新契约。
- **不影响**：L1/L2/L3/L4 解析链路、`QueryRouter`、搜索接口、配置文件、热更新机制。
