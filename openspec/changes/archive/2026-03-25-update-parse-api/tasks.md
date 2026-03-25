## 1. 新增请求/响应 Pydantic 模型

- [x] 1.1 在 `models/schemas.py` 中新增 `ParseApiRequest` 模型，包含字段：`source`（默认 `askbob`）、`user_text`（必填）、`session_id`、`trace_id`、`user_id`、`ts`、`user_action`（默认 `write`）、`action_scenario`（默认 `customerSearch`）、`extra_input_params`（默认 `{}`）
- [x] 1.2 在 `models/schemas.py` 中新增 `ParseApiExtraOutput` 模型，包含字段：`query`、`query_logic`、`conditions`、`matched_level`、`rewritten_query`、`matched_patterns`、`last_tims`
- [x] 1.3 在 `models/schemas.py` 中新增 `ParseApiData` 模型，包含字段：`robot_text`、`end_flag`（固定为 `1`）、`extra_output_params: ParseApiExtraOutput`、`trace_id`
- [x] 1.4 在 `models/schemas.py` 中新增 `ParseApiResponse` 模型，包含字段：`code`（int）、`msg`（str）、`data: Optional[ParseApiData]`

## 2. 更新路由层实现

- [x] 2.1 在 `routes.py` 中将 `/api/v1/parse` 的入参类型改为 `ParseApiRequest`，response_model 改为 `ParseApiResponse`
- [x] 2.2 在路由处理函数中将 `request.user_text` 传入 `QueryRouter`，替换原来的 `request.query`
- [x] 2.3 实现 `robot_text` 生成逻辑：`conditions` 非空时返回 `f"已解析 {len(conditions)} 个查询条件"`，否则返回 `"未能解析查询条件"`
- [x] 2.4 组装 `ParseApiResponse`：成功时 `code=0`、`msg="操作成功"`，`data.trace_id` 取自 `request.trace_id`
- [x] 2.5 将日志调用中的 `agent_id` 参数改为从 `request.user_id` 获取
- [x] 2.6 将异常处理改为返回 `ParseApiResponse(code=500, msg=str(e), data=None)`（HTTP 200），移除原有 `HTTPException(status_code=500)`

## 3. 回归测试

- [x] 3.1 新增或更新 `tests/test_parse_route.py`，覆盖场景：完整入参成功返回、仅传必填字段成功返回、有条件时 robot_text 正确、无条件时 robot_text 正确、trace_id 透传正确
- [x] 3.2 补充异常场景测试：模拟 `QueryRouter` 抛出异常，断言响应 HTTP 200 且 `code=500`
- [x] 3.3 运行 `pytest tests/test_parse_route.py -v` 确认全部用例通过