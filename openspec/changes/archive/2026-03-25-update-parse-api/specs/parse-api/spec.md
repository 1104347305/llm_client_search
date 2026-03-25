## ADDED Requirements

### Requirement: Parse API SHALL 接受 AskBob 标准协议入参
系统 MUST 接受包含 `source`、`user_text`、`session_id`、`trace_id`、`user_id`、`ts`、`user_action`、`action_scenario`、`extra_input_params` 的请求体。其中 `user_text` 为必填字段，`source` 默认为 `askbob`，`user_action` 默认为 `write`，`action_scenario` 默认为 `customerSearch`，`extra_input_params` 默认为空对象。

#### Scenario: 完整入参正常解析
- **WHEN** 调用方提交包含全部字段的合法请求体
- **THEN** 接口返回 200，`data.trace_id` 与入参 `trace_id` 一致，解析结果在 `data.extra_output_params` 中

#### Scenario: 仅传必填字段
- **WHEN** 调用方仅传 `user_text` 和 `user_id`，省略其他可选字段
- **THEN** 接口返回 200，使用默认值填充缺省字段，解析正常执行

### Requirement: Parse API SHALL 返回标准 Bot 协议响应结构
系统 MUST 以 `{ code, msg, data }` 结构返回响应。成功时 `code=0`、`msg="操作成功"`；`data` MUST 包含 `robot_text`、`end_flag`、`extra_output_params`、`trace_id` 四个字段。HTTP 状态码始终为 200。

#### Scenario: 成功解析返回标准结构
- **WHEN** 解析链路成功执行
- **THEN** 响应 JSON 顶层包含 `code=0`、`msg="操作成功"`，`data.end_flag=1`，`data.trace_id` 等于入参 `trace_id`

#### Scenario: extra_output_params 包含解析结果
- **WHEN** 解析链路成功执行
- **THEN** `data.extra_output_params` MUST 包含 `query`（原始 user_text）、`query_logic`、`conditions`、`matched_level`、`rewritten_query`、`matched_patterns`、`last_tims`

### Requirement: Parse API SHALL 生成 robot_text 意图摘要
系统 MUST 在响应 `data.robot_text` 中返回解析意图的自然语言摘要。有条件时返回「已解析 N 个查询条件」，无条件时返回「未能解析查询条件」。摘要由路由层规则生成，不调用 LLM。

#### Scenario: 有条件时返回条件数摘要
- **WHEN** 解析结果 `conditions` 非空
- **THEN** `data.robot_text` 为「已解析 N 个查询条件」，N 等于 conditions 列表长度

#### Scenario: 无条件时返回未解析摘要
- **WHEN** 解析结果 `conditions` 为空列表
- **THEN** `data.robot_text` 为「未能解析查询条件」

### Requirement: Parse API MUST 统一异常响应格式
系统 MUST 在内部异常时返回 HTTP 200，响应体为 `{ code: 500, msg: <错误信息>, data: null }`，不抛出 HTTP 500。

#### Scenario: 内部异常返回 code=500
- **WHEN** 路由在解析过程中抛出未处理异常
- **THEN** HTTP 状态码为 200，响应体 `code=500`，`msg` 包含异常描述文本，`data` 为 null
