# 评估集说明

更新时间：2026-05-17

## ungraded_client_search_queries.jsonl

这是从 `src/main/python/docs/测试集.txt` 固化出来的未标注评估集，共 427 条自然语言客户搜索问题。

每行格式：

```json
{"id":"q_0001","query":"张三","tags":["ungraded"]}
```

由于当前测试数据没有标准答案，本评估集不计算准确率，只用于观察：

- `api_success_rate`：解析接口是否稳定返回。
- `condition_non_empty_rate`：有多少问题产生结构化条件。
- `known_level_rate`：有多少问题命中已知解析层级。
- `level_distribution`：L1/L2/L4/unknown 分布。
- `avg_latency_ms` / `p95_latency_ms`：耗时表现。

运行方式：

```bash
python -m src.main.python.main
```

```bash
python -m src.main.python.tools.iteration_pipeline batch-eval \
  --input src/main/python/docs/eval_sets/ungraded_client_search_queries.jsonl \
  --output-dir src/main/python/docs/evaluations/ungraded_client_search_queries \
  --base-url http://localhost:8000 \
  --concurrency 4 \
  --progress-interval 10
```

如果后续人工补充标准答案，可以在对应行增加 `expected`：

```json
{"id":"q_0001","query":"高温客户","tags":["graded"],"expected":{"query_logic":"AND","conditions":[{"field":"clientTemperature","operator":"MATCH","value":"高温"}]}}
```

补齐 `expected` 后，`batch-eval` 会自动计算 `total_accuracy`、`exact_match_rate`、`field_match_rate`、`operator_match_rate` 等准确率指标。

## 候选标注文件

`ungraded_client_search_queries_label_candidates.xlsx` 和同名 `.jsonl` 是基于配置 examples、枚举值和 value mappings 生成的候选标注结果，用于人工 review。

候选标注统计：

- `auto_approved`：12
- `single_candidate_review`：93
- `conflict_review`：276
- `manual_required`：46

这些候选不是金标。正式用于准确率评估前，需要人工确认或修正后再写回 `expected`。

如果 `label-candidates` 覆盖率太低，可以改用意图候选标注：

```bash
python -m src.main.python.tools.iteration_pipeline intent-label-candidates \
  --input src/main/python/docs/eval_sets/my_queries.txt \
  --output src/main/python/docs/evaluations/my_queries_ungraded/intent_label_candidates.xlsx \
  --base-url http://localhost:8000 \
  --concurrency 4 \
  --write-jsonl
```

它会把当前解析接口返回的 `intent_summary` 也导出成中文候选，因此覆盖率更高。状态含义：

- `auto_approved`：配置候选高置信通过，可以抽查。
- `single_candidate_review`：静态候选单一，需要确认。
- `conflict_review`：静态候选冲突，优先人工看。
- `parser_review`：来自当前解析接口的中文意图候选，覆盖率高但必须复核。
- `manual_required`：没有候选或接口无可用结果。
- `api_error`：接口调用失败。

推荐做法是先筛 `auto_approved` 抽查入库，再集中 review `parser_review` 中业务高频或高价值样本；不要把 `parser_review` 直接当金标。

## 从 batch_eval_result.xlsx 生成意图标准答案

如果已经跑过 `batch-eval`，也可以直接基于输出的 `batch_eval_result.xlsx` 做人工分析，再生成 `intent-eval` 标准答案。

可以先生成带风险提示的审阅表：

```bash
python -m src.main.python.tools.iteration_pipeline prepare-intent-review \
  --input src/main/python/docs/evaluations/my_queries_observe/batch_eval_result.xlsx \
  --output src/main/python/docs/evaluations/my_queries_observe/intent_review.xlsx
```

这个命令会在 `cases` sheet 末尾自动增加：

- `review_status`
- `issue_type`
- `risk_level`
- `auto_suggestion`
- `final_intent_summary`
- `final_intent_lines`
- `skip`
- `review_comment`

自动预检会标出手机号/身份证/保单号字段疑似错误、否定语义丢失、OR 逻辑错误、范围 operator 疑似错误、空解析、unknown 层级、接口错误等。低风险样本会预填 `final_intent_summary`，高风险和中风险样本需要人工确认或修正。

然后打开 `intent_review.xlsx` 的 `cases` sheet，处理这些列：

| 列名 | 说明 |
| --- | --- |
| `review_status` | 人工结论。填 `通过` / `pass` / `correct` 表示当前 `intent_summary` 可作为标准答案。 |
| `issue_type` | 错误类型，例如 `missing_condition`、`extra_condition`、`condition_wrong`、`value_wrong`、`logic_wrong`、`unsupported_wrong`。 |
| `final_intent_summary` | 如果当前解析错了，在这里填写修正后的完整标准意图文本。 |
| `final_intent_lines` | 可选。如果不想写完整文本，可填写标准意图行，支持换行、分号或 JSON list。 |
| `skip` | 可选。填 `是` / `true` / `skip` 表示跳过该样本。 |

生成标准答案：

```bash
python -m src.main.python.tools.iteration_pipeline intent-gold-from-batch-excel \
  --input src/main/python/docs/evaluations/my_queries_observe/batch_eval_result.xlsx \
  --output src/main/python/docs/eval_sets/my_intent_eval.jsonl
```

生成规则：

- `review_status=通过/pass/correct`：使用原 `intent_summary` 作为 `expected_intent`。
- 有 `final_intent_summary`：使用修正后的完整意图文本作为 `expected_intent`。
- 有 `final_intent_lines`：使用修正后的意图行作为 `expected_intent_lines`。
- 标了错误类型但没有修正意图：跳过，并写入同名 `.skipped.jsonl`，避免把错结果变成金标。
- 不建议使用 `--accept-unreviewed`；它会把未复核行的 `intent_summary` 也当标准答案，只适合快速试跑。

然后正式评估：

```bash
python -m src.main.python.tools.iteration_pipeline intent-eval \
  --input src/main/python/docs/eval_sets/my_intent_eval.jsonl \
  --output-dir src/main/python/docs/evaluations/my_intent_eval \
  --base-url http://localhost:8000 \
  --concurrency 4
```

## Skill 评估

如果不想继续为每个 badcase 打补丁，可以使用 Skill 风格的评估入口。它会基于确定性预检规则和 `eval_skills/client_search_intent_eval/SKILL.md` 的 Rubric，把问题归类到更稳定的错误维度：

- `unparsed`
- `missing_condition`
- `extra_condition`
- `duplicate_condition_across_fields`
- `field_wrong`
- `operator_wrong`
- `value_wrong`
- `logic_wrong`
- `unsupported_handling_wrong`

运行：

```bash
python -m src.main.python.tools.iteration_pipeline skill-eval \
  --input src/main/python/docs/evaluations/my_queries_observe/batch_eval_result.xlsx \
  --skill src/main/python/docs/eval_skills/client_search_intent_eval/SKILL.md \
  --output-dir src/main/python/docs/evaluations/my_queries_skill_eval
```

输出：

- `skill_eval_result.json`：完整结构化结果。
- `skill_eval_result.xlsx`：可筛选的评估表。
- `skill_eval_report.md`：错误维度统计报告。
- `candidate_intent_gold.jsonl`：基于当前判分生成的候选意图标准答案，仍建议人工 review 后再入正式 gold set。

## intent_eval_sample.jsonl

这是意图文本评估的最小样例集。它支持两种标注方式：

1. 写 `expected.conditions`，评估器会调用现有 `IntentSummaryService` 生成标准意图行。
2. 直接写 `expected_intent_lines`，适合只想按业务中文意图验收的场景。

推荐优先使用第 1 种方式，因为字段名、operator 文案、连接词、特殊模板都来自：

```text
src/main/python/config/intent_summary_labels_args.yaml
```

例如：

```json
{"query":"45岁以上客户","expected":{"query_logic":"AND","conditions":[{"field":"clientAge","operator":"GTE","value":45}]}}
```

会按配置生成标准意图行：

```text
客户年龄≥45的客户
```

`intent-eval` 同时比较两类结果：

- 意图行集合：用于定位缺失意图和多余意图。
- 完整意图文本：用于检查 `query_logic` 连接词、空条件提示、不支持字段提示等文案是否完全一致。

因此下面这些场景也会按 `intent_summary_labels_args.yaml` 判分：

| 场景 | 标准文案来源 |
| --- | --- |
| 没有任何查询条件 | `messages.no_conditions`，例如“未识别到明确查询条件” |
| 有支持条件，也有不支持条件 | `unsupported_prefix` + 字段标签 + `unsupported_suffix_with_supported` |
| 条件非空但全部不支持 | `unsupported_prefix` + 字段标签 + `unsupported_suffix_without_supported` |
| `query_logic=AND` | `messages.connector_and`，例如“并且” |
| `query_logic=OR` | `messages.connector_or`，例如“或者” |
| `operator=GTE/LTE/CONTAINS/...` | `op_labels`，例如“≥”、“≤”、“包含” |

运行方式：

```bash
python -m src.main.python.tools.iteration_pipeline intent-eval \
  --input src/main/python/docs/eval_sets/intent_eval_sample.jsonl \
  --output-dir src/main/python/docs/evaluations/intent_eval_sample \
  --base-url http://localhost:8000 \
  --concurrency 4
```

输出文件：

- `intent_eval_result.json`：完整结果。
- `intent_failed_cases.jsonl`：意图文本不匹配或接口错误样本。
- `intent_report.md`：中文报告，展示缺失意图和多余意图。
- `intent_eval_result.xlsx`：Excel 汇总。
