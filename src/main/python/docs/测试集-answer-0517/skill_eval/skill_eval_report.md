# Skill 评估报告

生成时间：2026-05-18 17:06:59
输入文件：/Users/mickey/project/PA-ALG/llm_client_search/src/main/python/docs/测试集-answer-0517/batch_eval_result.xlsx

## 概览

- 样本总数：427
- pass_rate：98.83%
- fail_rate：1.17%
- uncertain_rate：0.00%

## 错误类型分布

| error_type | 数量 |
| --- | --- |
| duplicate_condition_across_fields | 1 |
| unparsed | 1 |
| value_wrong | 3 |

## 高优先级样本

| id | query | error_types | reason |
| --- | --- | --- | --- |
| q_0056 | 有除责条款的客户 | unparsed | 依据 SKILL.md：query 有可评估内容但未生成有效意图。 |
| q_0083 | 有没有A1养老险最近一年买保险保额比较高的人 | value_wrong | 依据 SKILL.md：购买/配置极性语义与 value 不一致，isBuyPension=有购买，应为没有购买。 |
| q_0328 | 中温B类有年金险已婚的 | value_wrong | 依据 SKILL.md：字段枚举值不合法，pCategorys=年金保险。 |
| q_0403 | 有产险但没寿险的 | value_wrong | 依据 SKILL.md：购买/配置极性语义与 value 不一致，isBuyProperty=有购买，应为没有购买。 |
| q_0427 | 1775 | duplicate_condition_across_fields | 依据 SKILL.md：同一 query 片段或 value 疑似被解析到多个字段，1775 -> clientMobile,clientNo,polNo；1775 -> clientNo,polNo；1775 -> clientMobile,clientNo。 |
