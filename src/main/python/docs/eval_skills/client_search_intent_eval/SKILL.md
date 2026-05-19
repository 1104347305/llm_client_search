# 客户搜索意图评估 Skill

## 任务

根据用户 query、actual_conditions、actual_intent_summary 判断客户搜索解析是否正确，并输出结构化错误分类、严重程度、原因和候选修正意图。

## 输入

- query：用户自然语言查询。
- actual_conditions：系统解析出的结构化条件。
- actual_intent_summary：系统根据 conditions 生成的中文意图文本。
- matched_level：命中的解析层级。
- deterministic_findings：确定性预检发现的问题。

## 输出 Schema

```json
{
  "verdict": "pass | fail | uncertain",
  "confidence": 0.0,
  "severity": "high | medium | low",
  "error_types": [],
  "reason": "",
  "expected_intent_summary": "",
  "expected_intent_lines": []
}
```

## 错误类型

- `unparsed`：query 有明确条件，但系统未识别或解析层级 unknown。
- `missing_condition`：少解析查询条件。
- `extra_condition`：多解析查询条件。
- `duplicate_condition_across_fields`：同一个查询条件或同一查询片段命中多个字段。
- `field_wrong`：查询字段错误。
- `operator_wrong`：操作符错误，例如否定、范围、大小比较处理错误。
- `value_wrong`：value 错误，例如非法枚举值、截断值、归一化错误。
- `logic_wrong`：AND / OR 逻辑错误。
- `unsupported_handling_wrong`：不支持字段提示错误。

## 判断准则

### 字段与枚举

- 最高优先级：只能接受参考字段定义中明确列出的字段名。若 actual_conditions 使用了不存在、拼错、或自行编造的 field，应判 `field_wrong`；生成 `expected_intent_summary` 时必须删除该条件。
- 若 query 中存在明确意图，但该意图在参考字段定义中没有可支持字段，应按“不支持字段”处理，而不是编造字段或输出错误条件。
- 判断 `value` 是否正确时，必须先定位字段，再查字段枚举配置；枚举配置优先级高于启发式规则。
- 字段枚举值以 `field_enums_args.yaml` 以及项目中同类 `*_enum_args.yaml` / `*_enums_args.yaml` 配置为准。只要 value 属于该字段枚举，就不能仅因为 value 较短、是单个英文字符、或出现在更长 query 片段中而判为 `value_wrong`。
- 若枚举配置中存在 `ordered: true`，表示该枚举按配置顺序从低到高排序。此类枚举的比较词必须展开为枚举集合，而不是使用数值 `GTE/LTE/GT/LT`：`x以上/x以下` 不包含边界值；`x及以上/x及以下` 包含边界值。
- 例如 `newValueLabel` 顺序为 `F<E<D<C<B<A4<A3<A2<A1`：`B以上` 应为 `["A4","A3","A2","A1"]`，`B及以上` 应为 `["B","A4","A3","A2","A1"]`，`B以下` 应为 `["F","E","D","C"]`，`B及以下` 应为 `["F","E","D","C","B"]`。
- 有序枚举比较中的口语别名可通过 `value_mappings_args.yaml` 辅助归一化，但该文件不是唯一依据。即使口语表述未出现在 mapping 中，只要 actual_conditions / actual_intent_summary 的标准枚举集合与 query 语义等价，也应判正确。例如 `本科以上` 输出 `["硕士研究生","博士研究生","博士后"]` 是正确的。
- 若字段没有枚举约束，或 value 是数值、日期、布尔/存在性、派生范围等非枚举值，不应按“枚举值是否等于 query 原词”判断。只要解析出的 field、operator、value 能准确表达 query 意图，即判正确。
- 允许合理语义展开：例如 `未成年子女` 可解析为 `有子女` 且 `子女年龄≤17`；这不是 value 错误，也不是多条件错误。评估 `actual_intent_summary` 时不强制把家庭成员年龄、子女年龄、父母年龄、配偶年龄等成员年龄条件换算成出生日期范围，只要意图文本能准确表达年龄语义即可。
- 启发式截断判断只用于配置枚举无法确认、且 query 中存在明显更长实体词被拆成短 value 的情况。
- 若 value 不在该字段枚举中，应优先判为 `value_wrong`；如果它明显来自另一个字段或实体词，还应结合实际情况判 `field_wrong` 或 `extra_condition`。
- 生成 `expected_intent_summary` 时，应保留枚举合法的条件，删除或修正枚举非法、字段错配、重复解析的条件。

### 操作符

- 数值/日期字段，除 `clientAge`、`birthdayMd` 特例外，按 query 关键词判断 operator：`以上/及以上/≥/>=` -> `GTE`；`以下/及以下/≤/<=` -> `LTE`；`超过/大于/高于/>` -> `GT`；`低于/小于/少于/<` -> `LT`；精确值或无比较词区间 -> `RANGE`。
- 字符串字段才可使用 `MATCH`；数组/多值字符串字段使用 `CONTAINS` / `NOT_CONTAINS`；有无数据使用 `EXISTS` / `NOT_EXISTS`。
- 数值字段的精确值不能用 `MATCH`，应使用 `RANGE {"min": x, "max": x}`；例如 `45岁` 应为年龄 `RANGE {min:45,max:45}`，`年交保费30万以上` 应为 `annPremSegNum GTE 300000`，不能同时额外输出 `MATCH 300000`。
- 缺口查询应以参考字段定义中 `operator: NOT_CONTAINS` / `operator: NOT_EXISTS` 的用法为准，不能只凭某个否定字面硬判。若 query 命中这类负向用法，应使用 `NOT_CONTAINS` 或 `NOT_EXISTS`，不能输出正向包含条件；若 query 中的“未/无/非”等字只是业务词或年龄词的一部分，例如 `未成年/未成年人/没成年`，应按对应业务语义判断，不按缺口查询处理。
- 正向持有、配置、购买类表达，例如 `配置了/有/买了/购买了/持有`，应按正向语义判断。不能仅因为某个字段定义里存在 `NOT_CONTAINS` 用法，或 query 含有保险名/枚举值，就推断为缺口查询。
- `clientAge` 特例：`50岁以上/45岁及以上` -> `GTE 50/45`；`大于50岁/超过50岁` -> `GTE 51`；`50岁以下/45岁及以下` -> `LTE 50/45`；`小于50岁/低于50岁` -> `LTE 49`；`40岁左右` -> `RANGE {min:35,max:45}`。
- 单位换算：`万` -> `10000`，`千` -> `1000`；未明确单位时不做额外换算。

### 时间与逻辑

- 涉及相对时间时，必须按评估运行时的当前日期换算为具体日期范围，不能输出尖括号占位符。
- 必须区分自然周期和滚动周期：`下周/下星期/下个星期` 是下一个自然周；`未来一周/未来7天/接下来7天` 是从今天开始连续 7 天；`下个月/下月` 是下个自然月；`未来一月/未来一个月/未来30天` 是从今天开始连续 30 天。
- 默认 `query_logic` 为 `AND`。多个不同字段组合筛选、或 query 使用 `和/以及/同时/还有` 时，必须为 `AND`。
- 只有 query 明确出现 `或者/或/任一/之一`，且条件指向不同字段、语义是满足任一即可时，才可使用 `OR`。
- 同一数组字段内的 A 或 B，优先用一个 `CONTAINS` 多值条件表达；例如 `买了两全险或年金险` 可以是一个险种字段 `CONTAINS ["两全险","年金"]`，不一定使用全局 `OR`。

### 意图文本与重复

- 判断重复解析时，以结构化条件为准：同一 query 片段或同一 value 被解析到多个查询字段，才算 `duplicate_condition_across_fields` 或 `extra_condition`；仅意图文本的字段名/key/短词重复，但实际查询字段不同、value 不重复，不算失败。
- 不支持字段只评估“不支持字段是否判定正确”和提示文案是否符合支持条件数量。若不支持字段识别正确，即使 supported conditions 为空，也不应按 `missing_condition`、`unparsed` 或少条件失败处理。
- 例如 `提示：投保日期暂不支持搜索，无法进行查询。`、`提示：犹豫期时间暂不支持搜索，无法进行查询。` 这类 unsupported-only 输出，在字段判断正确时默认判 `pass`。
- unsupported-only 场景无需展示具体 value、operator 或范围边界；即使 query 中包含 `50万以上`、`今年` 等具体约束，也只需提示对应字段暂不支持。此类结果不应因缺少 `≥/≤/RANGE/value` 被判 `operator_wrong` 或 `value_wrong`。
- 若 query 同时包含支持字段和不支持字段，应保留支持字段意图，并追加 `提示：xx暂不支持搜索，系统将按可支持字段搜索。`；只要支持字段和不支持字段都判断正确，也默认判 `pass`。
- 意图文本必须由 `intent_summary_labels_args.yaml` 的字段名、operator 表述、连接词和不支持提示生成。若 conditions 正确但意图文本 operator 或连接词错误，应判 `operator_wrong` 或 `logic_wrong`。
- `deterministic_findings` 是预检提示，不是最终裁决。若预检结论与 query 语义、字段定义或本 skill 准则冲突，应以语义复核结果为准覆盖预检。例如 unsupported-only 被标记 `operator_wrong`、正向 `配置了` 被标记 `negation_missing` 时，若意图语义正确，应判 `pass`。

## 领域规则

- 默认按“是否完全符合 query 意图”判断，不要求 actual_intent_summary 与 query 原词逐字一致。只要解析出的字段、operator、value、query_logic 能完整、准确表达 query，就判正确。
- 允许合理语义展开、归一化和组合条件表达。例如 `未成年子女` 可解析为 `有子女` 且 `子女年龄≤17`；口语表述可归一化为标准枚举或标准字段值；同一业务意图也可用多个必要条件共同表达。
- 不要因为意图文本中的字段名、key、业务词重复就直接判失败。只有同一 query 片段或同一 value 被错误解析到多个字段，或产生了 query 没有表达的额外条件，才判 `duplicate_condition_across_fields` / `extra_condition`。
- 枚举字段需使用配置中的标准枚举值；非枚举字段、数值/日期范围、存在性条件、派生条件则看语义是否等价，不按 query 原词是否等于 value 判断。
- 有序枚举、口语组别、别名表达应按语义和最终展开集合判断。配置和 mapping 是重要依据，但不是唯一依据；若输出集合符合 query 的边界和范围语义，应判正确。

### 特殊说明

- 保单状态需要区分“缴费有效/交费有效”和“保单有效”：`缴费有效/交费有效` 只表示 `polNoInfo.polStatus CONTAINS ["交费有效"]`；`保单有效/有效保单/保单生效/保单状态有效` 表示 `["交费有效","自垫交清","交清","减额交清","免交","自垫有效"]`。
- 不支持字段提示必须使用 `intent_summary_labels_args.yaml`：若只有不支持字段且最终 supported conditions 为空，输出 `提示：xx暂不支持搜索，无法进行查询。`；若同时存在 supported conditions，先输出可支持意图，再输出 `提示：xx暂不支持搜索，系统将按可支持字段搜索。`。
- `assetsCondition` 有特殊枚举展开：`有车` 应为 `["有车","有房有车"]`，`有房` 应为 `["有房","有房有车"]`，`有车有房/有房有车` 应为 `["有房有车"]`，`有车无房` 应为 `["有车"]`，`无车有房` 应为 `["有房"]`，`无车无房/无房无车` 应为 `["无房无车"]`。
- 意图文本中的 operator、连接词、不支持字段提示应来自 `intent_summary_labels_args.yaml`。
- 是否有保单托管可以解析为托管标志：有保单托管=托管标志为是；没有保单托管=托管标志为否。
- 若意图为“暂时没判读出这组数据代表什么，已帮您在手机号、客户号、保单号中一起查找匹配的客户”一律默认 `pass`
- 居家意向=居家潜客不属于居家会员客户；居家养老客户=居家客户=v0.5、v1、v1.5、v2、v2.5、v3；
- 康养客户=逸享会员、逸享PLUS会员、颐享家会员、臻享会员V1、臻享会员V2、臻享会员V3
- 买了保险的客户=客户类型为：客户、准客；没买保险的客户=客户类型为：用户