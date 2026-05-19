# 批量问题自动化评估报告

生成时间：2026-05-19 10:57:34
输入文件：/Users/mickey/project/PA-ALG/llm_client_search/src/main/python/docs/测试集-550.txt

## 概览

- 样本总数：549
- 已标注样本：0
- 未标注样本：549
- graded_coverage_rate：0.00%
- api_success_rate：100.00%
- condition_non_empty_rate：99.09%
- known_level_rate：100.00%
- total_accuracy：N/A
- exact_match_rate：N/A
- field_match_rate：N/A
- operator_match_rate：N/A
- empty_rate：N/A
- false_positive_rate：N/A
- avg_latency_ms：1116.68
- p95_latency_ms：1891.43
- error_count：0

## 层级分布

| matched_level | 数量 |
| --- | --- |
| 2 | 125 |
| 4 | 424 |

## 失败样本

| id | query | 归因 |
| --- | --- | --- |
| - | - | 无 |

## 标注建议

- 当前输入没有 expected 标准答案，本次报告只统计解析层级、耗时和接口错误。
- 后续可以把问题改成 JSONL/CSV，并补 expected.conditions，即可自动计算准确率。
