# 04-Schema与配置说明

## 接口 Schema

文件：

```text
src/main/python/models/schemas.py
```

核心模型：

| 模型 | 说明 |
| --- | --- |
| `ParseApiRequest` | AskBob 标准协议入参 |
| `ParseApiResponse` | AskBob 标准协议出参 |
| `ParseApiData` | 响应 data 层 |
| `ParseApiExtraOutput` | 解析结果详情 |
| `Condition` | 单个搜索条件 |
| `RangeValue` | 范围值 |
| `QueryLogic` | `AND` / `OR` |
| `Operator` | 查询操作符 |
| `SearchRequest` | 内部结构化搜索请求 |
| `NaturalLanguageSearchRequest` | 内部自然语言搜索请求 |
| `SearchResponse` | 内部搜索响应 |

## Condition

结构：

```json
{
  "field": "clientBirthday",
  "operator": "LTE",
  "value": "1981-12-31 00:00:00"
}
```

字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `field` | string | 下游搜索字段名 |
| `operator` | enum | 查询操作符 |
| `value` | string/number/object/list/null | 查询值 |

`Condition` 内有自动归一逻辑：

- `CONTAINS` / `NOT_CONTAINS` 的 value 会规范为 list。
- 其他 operator 收到 list 时会取第一个值。
- `EXISTS` / `NOT_EXISTS` 不需要 value。

## Operator

当前支持：

| Operator | 含义 |
| --- | --- |
| `MATCH` | 精确或匹配查询 |
| `GT` | 大于 |
| `GTE` | 大于等于 |
| `LT` | 小于 |
| `LTE` | 小于等于 |
| `RANGE` | 范围 |
| `CONTAINS` | 包含，value 为列表 |
| `NOT_CONTAINS` | 不包含，value 为列表 |
| `EXISTS` | 字段存在且不为空 |
| `NOT_EXISTS` | 字段不存在或为空 |

`RANGE` 值示例：

```json
{
  "field": "clientAge",
  "operator": "RANGE",
  "value": {
    "min": 30,
    "max": 45
  }
}
```

## 字段意图 Schema

文件：

```text
src/main/python/config/field_definitions_args.yaml
```

当前规模：179 条 intent。

典型结构：

```yaml
intents:
  - id: client_age_gte
    field: clientAge
    operator: GTE
    value_type: number
    retrieval_text: 年龄大于等于 某年龄以上
    enum: null
    unit: 岁
    notes: 客户本人年龄
    examples:
      - query: 45岁以上的客户
        value: 45
    negative_examples: []
```

字段用途：

| 字段 | 作用 |
| --- | --- |
| `id` | intent 唯一标识 |
| `field` | 输出到 Condition 的字段名 |
| `operator` | 输出到 Condition 的 operator |
| `value_type` | 值类型提示 |
| `retrieval_text` | RAG 检索主文本 |
| `enum` | 可选枚举 |
| `unit` | 单位 |
| `notes` | 给 LLM 的字段说明 |
| `examples` | 正例 |
| `negative_examples` | 反例 |

这个文件同时承担三件事：

- 合法字段基准。
- L4 RAG 知识库。
- 新字段开发入口。

## 字段映射配置

文件：

```text
src/main/python/config/field_mapping_args.yaml
```

当前规模：

```text
query_fields: 12
field_context_groups: 2
```

代码入口：

```text
src/main/python/models/field_mapping.py
```

常用方法：

```python
get_query_field("customer_name")
get_field_context_group("...")
get_sensitive_field_group("...")
get_name_candidate_values("...")
```

用途：

- 给 L1 和部分后处理提供字段别名。
- 配置敏感字段组。
- 配置家庭成员/客户本人等上下文分组。
- 配置裸姓名候选识别。

## L2 规则配置

文件：

```text
src/main/python/config/enhanced_rules_args.yaml
```

当前规模：

```text
rules: 417
composite_rules: 70
pattern_vars: 3
```

`pattern_vars` 用于抽取规则中高频复用的正则片段，当前包括：

| 变量 | 说明 |
| --- | --- |
| `CW` | 中文、标点和空白连接字符范围。 |
| `SEARCH` | 查询/查找/帮我看看等检索意图前缀。 |
| `CUSTOMER_SUFFIX` | 查询末尾的客户、人、名单等对象后缀：`(?:的客户|客户|有哪些客户|有哪些人|名单|的人|人)?`。 |

常见规则形态：

```yaml
- name: "客户年龄大于等于"
  field: "clientAge"
  operator: "GTE"
  value_type: "capture"
  patterns:
    - "(\\d+)岁以上"
```

枚举规则形态：

```yaml
- name: "购买产品"
  field: "polNoInfo.plancodeinfo.abbrname"
  operator: "CONTAINS"
  value_type: "capture"
  enum_ref: "polNoInfo.plancodeinfo.abbrname"
  patterns_template:
    - "买过{enum}"
    - "购买了{enum}"
```

## 枚举配置

普通枚举：

```text
src/main/python/config/field_enums_args.yaml
```

当前规模：34 个枚举字段。

大枚举文件：

```text
src/main/python/config/planAbbrNames_enums_args.yaml
src/main/python/config/profName_enums_args.yaml
src/main/python/config/polNoInfo.plancodeinfo.abbrname_enums_args.yaml
src/main/python/config/polNoInfo.plancodeinfo.planfullname_enums_args.yaml
src/main/python/config/polNoInfo.claimdatainfo.claimplancodename_enums_args.yaml
```

作用：

- L2 `{enum}` 展开。
- L4 Trie 精确枚举召回。
- 字段值标准化。

## 值归一化

文件：

```text
src/main/python/config/value_mappings_args.yaml
```

当前规模：23 个字段映射。

用途：

- 把口语值映射成标准枚举值。
- 在 query 预处理阶段重写用户输入。
- 在 L4 输出阶段做字段级 value 标准化。

示例场景：

```text
男士、男性、男 -> 男
女士、女性、女 -> 女
```

## 意图摘要配置

文件：

```text
src/main/python/config/intent_summary_labels_args.yaml
```

顶层 key：

```text
field_labels
op_labels
messages
date_labels
family_templates
profile_phrases
```

作用：

- 将 conditions 转成人类可读 `robot_text`。
- 生成 `intent_summary`。

## 运行配置

文件：

```text
src/main/python/config/dev_client_search_args.yaml
src/main/python/config/stg_client_search_args.yaml
src/main/python/config/prd_client_search_args.yaml
```

关键项：

```yaml
API_HOST: "0.0.0.0"
API_PORT: 8000
API_RELOAD: true

LLM_MODEL: "qwen3-next-80b-a3b-instruct"
LLM_API_KEY: "..."
LLM_BASE_URL: "https://dashscope.aliyuncs.com/compatible-mode/v1"
LLM_TEMPERATURE: 0.1
LLM_MAX_TOKENS: 2000

SEARCH_API_BASE_URL: "http://localhost:8081"

ES_HOST: "http://localhost:9200"
ES_FIELD_INDEX: "field_intents"
ES_ANALYZER: "ik_max_word"

ENABLE_L1: true
ENABLE_L2: true
ENABLE_L3: true
ENABLE_L4: true
ENABLE_L4_RAG_ES: true
ENABLE_L4_RAG_TRIE: true
ENABLE_L4_RAG_L2: true

ENABLE_PARSE_RESPONSE_AES: false
```

注意：

- YAML 里当前存在明文 LLM API key，建议后续迁到环境变量或密钥管理系统。
- `ENABLE_L3=true` 不代表主链路真的启用了 L3，当前代码中 L3 调用被注释。
