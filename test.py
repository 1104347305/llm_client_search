from openai import OpenAI
import os
import time

startTime = time.perf_counter()

client = OpenAI(
    # 如果没有配置环境变量，请用阿里云百炼API Key替换：api_key="sk-xxx"
    api_key='sk-03b30a83b16d4b40b7da585d54776712',
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

prompt = '''你是一个专业的客户搜索查询分析专家。你的任务是将用户的自然语言查询转换为结构化的搜索条件。

## 核心约束（最高优先级）

**只能使用下方"参考字段定义"中明确列出的字段名（field）。**
若查询意图找不到匹配的参考字段，该意图对应的条件必须忽略（不输出）。
若参考字段给出了明确的枚举值（enum），必须使用给定的枚举值。
禁止自行推断或编造字段名。

### 相关字段参考（根据查询内容动态召回）

- **productCode** | 操作符: CONTAINS | 值类型: enum | 枚举: ['生财宝', '智能星', '金利多', '平安永福', '平安康泰', '盛世金越']
  示例: "持有平安永福的客户" → {'field': 'productCode', 'operator': 'CONTAINS', 'value': '平安永福'}
- **isBuyPregnancyCar** | 操作符: MATCH | 值类型: enum | 枚举: ['车险', '非车险']
  示例: "持有车险的客户" → {'field': 'isBuyPregnancyCar', 'operator': 'MATCH', 'value': '车险'}
  示例: "有非车险的客户" → {'field': 'isBuyPregnancyCar', 'operator': 'MATCH', 'value': '非车险'}
- **assetsCondition** | 操作符: MATCH | 值类型: enum
  示例: "有车的客户" → {'field': 'assetsCondition', 'operator': 'MATCH', 'value': '有车'}
  示例: "没有车的客户" → {'field': 'assetsCondition', 'operator': 'MATCH', 'value': '没车'}
- **clientBirthday** | 操作符: RANGE | 值类型: date | 格式: yyyy-MM-dd
  示例: "1990年出生的客户" → {'field': 'clientBirthday', 'operator': 'RANGE', 'value': {'min': '1990-01-01', 'max': '1990-12-31'}}
  示例: "1985年5月出生的客户" → {'field': 'clientBirthday', 'operator': 'RANGE', 'value': {'min': '1985-05-01', 'max': '1985-05-31'}}
- **clientTemperature** | 操作符: MATCH | 值类型: enum | 说明: 根据客户活跃度分类，温度从低到高：冷却<低温<中温<高温；联系频次低、没有联系---》低温；联系频繁、最近有联系--》高温
  示例: "高温客户" → {'field': 'clientTemperature', 'operator': 'MATCH', 'value': '高温'}
- **birthdayMd** | 操作符: RANGE | 值类型: date | 格式: MM-dd | 说明: 只含月日（不含年），格式MM-dd；本月生日 → 当前月01到当前月-31
  示例: "3月15日生日的客户" → {'field': 'birthdayMd', 'operator': 'MATCH', 'value': '03-15'}
  示例: "本月生日的客户" → {'field': 'birthdayMd', 'operator': 'RANGE', 'value': {'min': '当前月-01', 'max': '当前月-31'}}
- **zhenxiangRunEquityGrade** | 操作符: MATCH | 值类型: enum | 枚举: ['国内版', '国际版']
  示例: "有安有护国际版的客户" → {'field': 'zhenxiangRunEquityGrade', 'operator': 'MATCH', 'value': '国际版'}
  示例: "持有安有护权益的客户" → {'field': 'zhenxiangRunEquityGrade', 'operator': 'EXISTS', 'value': None}
- **clientNameNew** | 操作符: MATCH | 值类型: extract
  示例: "叫张三的客户" → {'field': 'clientNameNew', 'operator': 'MATCH', 'value': '张三'}
  示例: "名字是李四的客户" → {'field': 'clientNameNew', 'operator': 'MATCH', 'value': '李四'}
- **trusteeshipFlag** | 操作符: MATCH | 值类型: enum
  示例: "有保单托管的客户" → {'field': 'trusteeshipFlag', 'operator': 'MATCH', 'value': '是'}
  示例: "未托管的客户" → {'field': 'trusteeshipFlag', 'operator': 'MATCH', 'value': '否'}
- **vipType** | 操作符: MATCH | 值类型: enum | 说明: 口语映射：黄金→黄金V1，铂金→铂金V1
  示例: "铂金V1会员" → {'field': 'vipType', 'operator': 'MATCH', 'value': '铂金V1'}
  示例: "原黄金VIP客户" → {'field': 'vipType', 'operator': 'MATCH', 'value': '原黄金VIP'}

## 操作符说明
- **MATCH**: 精确/模糊匹配
- **CONTAINS**: 数组字段包含某值
- **NOT_CONTAINS**: 数组字段不包含某值（缺口查询）
- **EXISTS / NOT_EXISTS**: 字段有/无数据
- ****: 大于等于 / 小于等于（数值）
- **GTE/LTE/RANGE**: 大于等于/小于等于/区间范围（精确年龄使用RANGE表述，如：45岁--》{"min": 45, "max": 45}）

## 通用规则
- 缺口查询（未配置/没有/未购买/缺少）→ NOT_CONTAINS
- 数值：20万→200000，万=×10000，千=×1000
- **MATCH 仅用于字符串字段；数值字段（age/annual_income等）只用 GTE/LTE/RANGE，精确值用 RANGE {min:x, max:x}**
- 学历层级升序：高中<中专<大学专科<大学本科<硕士研究生<博士研究生<博士后
- 客户温度升序：冷却<低温<中温<高温

## AND 与 OR 的使用规则（极其重要，严禁混淆）

### query_logic: AND（默认，绝大多数情况）
**含义：所有条件同时满足**
- 查询涉及**多个不同字段**的组合筛选时，需所有条件都满足，永远用 AND
- 例：45岁以上，已婚，年收入20万以上 → AND
- 例：没有买过养老险且有小孩 → AND

### query_logic: OR（极少使用，严格限制）
**含义：多个完全不同的独立条件，满足任意一个即可**
- **只有**查询中明确含有"或者"、"任一"等语义，且条件指向**不同字段**时才用 OR
- 例："年龄超过60岁或者年收入超过100万" → OR（两个不同字段）

**同一字段匹配多个候选值时，必须使用 CONTAINS，而非 OR + 多条 MATCH，例如：高温或中温的客户--》{"field": "customer_temperature", "operator": "CONTAINS", "value": ["高温","中温"]}**


## 输出格式（严格 JSON，不加任何其他文字）

{"query_logic": "AND", "conditions": [{"field": "字段名", "operator": "操作符", "value": "值"}]}

## 示例

"45岁以上、已婚、年收入20万以上且没买过养老险"
{"query_logic":"AND","conditions":[{"field":"age","operator":"GTE","value":45},{"field":"marital_status","operator":"MATCH","value":"已婚"},{"field":"annual_income","operator":"GTE","value":200000},{"field":"held_product_category","operator":"NOT_CONTAINS","value":"年金保险"}]}

"本科学历以上的客户"（同一字段多值 → CONTAINS，不是 OR）
{"query_logic":"AND","conditions":[{"field":"education","operator":"CONTAINS","value":["大学本科","硕士研究生","博士研究生","博士后"]}]}

"年龄超过60岁或者年收入超过100万的客户"（不同字段，明确"或者" → OR）
{"query_logic":"OR","conditions":[{"field":"age","operator":"GTE","value":60},{"field":"annual_income","operator":"GTE","value":1000000}]}

"45岁的女性客户"（精确年龄需要使用RANGE表述，min=max=具体年龄）
{"query_logic":"AND","conditions":[{"field":"age","operator":"RANGE","value":{"min": 45, "max": 45}},{"field":"gender","operator":"MATCH","value":"女"}]}

"40岁左右的客户"（年龄左右需要使用RANGE表述）
{"query_logic":"AND","conditions":[{"field":"age","operator":"RANGE","value":{"min": 38, "max": 42}}]}

### 用户查询
有哪些客户买了盛世金越，但是没有买生财宝'''

messages = [{"role": "user", "content": prompt}]
completion = client.chat.completions.create(
    model="qwen3.5-27b",  # 您可以按需更换为其它深度思考模型
    messages=messages,
    extra_body={"enable_thinking": False},
    stream=False
)
is_answering = False  # 是否进入回复阶段
print("\n" + "=" * 20 + "思考过程" + "=" * 20)
print(completion.choices[0].message.content)
print('耗时：', time.perf_counter() - startTime)
