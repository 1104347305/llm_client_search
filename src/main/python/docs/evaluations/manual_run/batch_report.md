# 批量问题自动化评估报告

生成时间：2026-05-17 13:27:26
输入文件：/Users/mickey/project/PA-ALG/llm_client_search/src/main/python/docs/测试集.txt

## 概览

- 样本总数：100
- 已标注样本：0
- 未标注样本：100
- total_accuracy：N/A
- exact_match_rate：N/A
- field_match_rate：N/A
- operator_match_rate：N/A
- empty_rate：N/A
- false_positive_rate：N/A
- avg_latency_ms：29229.97
- p95_latency_ms：30009.44
- error_count：0

## 层级分布

| matched_level | 数量 |
| --- | --- |
| 2 | 3 |
| 4 | 1 |
| unknown | 96 |

## 失败样本

| id | query | 归因 |
| --- | --- | --- |
| - | - | 无 |

## 标注建议

- 当前输入没有 expected 标准答案，本次报告只统计解析层级、耗时和接口错误。
- 后续可以把问题改成 JSONL/CSV，并补 expected.conditions，即可自动计算准确率。
