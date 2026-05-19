# Skill 评估报告

生成时间：2026-05-19 11:00:13
输入文件：/Users/mickey/project/PA-ALG/llm_client_search/src/main/python/docs/测试集-550-answer-0517/batch_eval_result.xlsx

## 概览

- 样本总数：549
- pass_rate：94.72%
- fail_rate：5.28%
- uncertain_rate：0.00%

## 错误类型分布

| error_type | 数量 |
| --- | --- |
| duplicate_condition_across_fields | 3 |
| operator_wrong | 1 |
| unparsed | 4 |
| value_wrong | 21 |

## 高优先级样本

| id | query | error_types | reason |
| --- | --- | --- | --- |
| q_0059 | 有车险而且资产标签里带车的客户 | duplicate_condition_across_fields | 依据 SKILL.md：同一 query 片段或 value 疑似被解析到多个字段，有车险 -> assetsCondition,isBuyInsuranceCar。 |
| q_0116 | 给我拉一批本科以上、做医生的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，education=大学本科生,硕士研究生,博士研究生,博士后 -> 硕士研究生,博士研究生,博士后。 |
| q_0121 | 帮我查只有房没有车的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房,有房有车 -> 有房。 |
| q_0134 | 有车险、而且资产标签也带车的客户给我查下 | duplicate_condition_across_fields | 依据 SKILL.md：同一 query 片段或 value 疑似被解析到多个字段，有车险 -> assetsCondition,isBuyInsuranceCar。 |
| q_0145 | 看下社会中坚里已婚又有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0161 | 帮我找父母岁数大、自己名下还有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0163 | 有没有生日快到了而且已婚的客户 | operator_wrong | 依据 SKILL.md：query 命中字段定义中的 NOT_CONTAINS/NOT_EXISTS 负向用法，但结果未体现负向 operator 或文案。 |
| q_0180 | 有没有年交二十万以上、保额一百万以上的客户 | unparsed | 依据 SKILL.md：query 有可评估内容但未生成有效意图。 |
| q_0201 | 未婚、做律师、A2、高温且有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0213 | 居家意向、康养预达标会员、中温且有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0222 | 家里父母70岁以上、自己已婚、名下有房、还是在职有效客户的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0234 | 父母年纪比较大、自己又有房、还是社会中坚的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0238 | 看一下家里父母是1955年前出生、自己已婚、还有房、而且温度不错的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0245 | 有没有家里父母70岁以上、自己还是已婚女客户、而且名下有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0250 | 给我看看已婚、社会中坚、父母70岁以上、自己又有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0256 | 父母年纪比较大、自己又有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0371 | 有车的，未配置百万医疗的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有车 -> 有车,有房有车。 |
| q_0390 | 父母70岁以上、自己名下有房、还是在职有效客户的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0396 | 叫张晨、手机号18610000001、身份证号也能对上、而且已婚的客户 | duplicate_condition_across_fields | 依据 SKILL.md：同一 query 片段或 value 疑似被解析到多个字段，18610000001 -> clientMobile,idNo。 |
| q_0402 | 家里父母是1955年前出生的、自己已婚、社会中坚、还有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0409 | 做老师、已婚、B档、黄金V2、还有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0412 | 居家意向、康养预达标会员、中温而且有房的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0415 | 有房没车、最近有点冷、但短险里带意健险的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车；assetsCondition=有车,有房有车 -> 有房,有房有车。 |
| q_0420 | 父母70岁以上、自己已婚、还有房、而且是社会中坚的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0434 | 父母是1955年前出生、自己有房、还属于在职有效客户的客户 | value_wrong | 依据 SKILL.md：特殊字段业务语义未完整展开，assetsCondition=有房 -> 有房,有房有车。 |
| q_0531 | 客户已退保的原因是什么 | unparsed | 依据 SKILL.md：query 有可评估内容但未生成有效意图。 |
| q_0537 | 保单缴费期限为10年的客户 | unparsed | 依据 SKILL.md：query 有可评估内容但未生成有效意图。 |
| q_0541 | 生存金领取时间为2026-05-01的客户 | unparsed | 依据 SKILL.md：query 有可评估内容但未生成有效意图。 |
| q_0548 | 没买过e生保但买过健康险的客户 | value_wrong | 依据 SKILL.md：购买/配置极性语义与 value 不一致，isBuyHealth=有购买，应为没有购买。 |
