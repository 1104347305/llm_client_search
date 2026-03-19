# L2 Pattern 配置说明文档

**版本**: v1.0
**最后更新**: 2026-03-15
**维护者**: 开发团队

---

## 目录

1. [概述](#概述)
2. [配置文件结构](#配置文件结构)
3. [规则类型](#规则类型)
4. [占位符系统](#占位符系统)
5. [值转换器](#值转换器)
6. [复合规则](#复合规则)
7. [常见问题与解决方案](#常见问题与解决方案)
8. [最佳实践](#最佳实践)
9. [更新日志](#更新日志)

---

## 概述

L2 Enhanced Matcher 是基于 YAML 配置的灵活规则匹配引擎，支持：
- 正则表达式模式匹配
- 枚举值自动展开
- 值预处理与归一化
- 复合规则（多条件组合）
- 动态日期范围计算

**核心文件**:
- 配置文件: `config/enhanced_rules.yaml`
- 实现代码: `app/core/level2_enhanced_matcher.py`
- 枚举值目录: `config/enums/`

---

## 配置文件结构

### 主要部分

```yaml
# 1. 模式变量定义
pattern_vars:
  CW: '[，,。\.？\?\！! ：\:\u4e00-\u9fa5]'
  SEARCH: '(?:(?:查找|查询|找|找一下|查一下|检索|搜索)(?:一下|下)?(?:[，, ]{0,2}))?'

# 2. 规则列表
rules:
  - name: "规则名称"
    patterns: [...]
    field: "字段名"
    operator: "操作符"
    value_type: "值类型"
    value: {...}
    priority: 优先级

# 3. 复合规则
composite_rules:
  - name: "复合规则名称"
    patterns: [...]
    priority: 优先级

# 4. 枚举值定义
enum_values:
  字段名: [值1, 值2, ...]

# 5. 外部枚举文件
enum_files:
  字段名: "相对路径"

# 6. 值映射（别名归一化）
value_mappings:
  字段名:
    别名: "标准值"

# 7. 否定词列表
negation_words: [...]

# 8. 持有词列表
position_words: [...]
```

---

## 规则类型

### 1. 基础规则

直接定义 patterns 的规则：

```yaml
- name: "姓名-匹配"
  patterns:
    - '{SEARCH}(?:的客户|客户)?(?:叫|名叫|姓名是)([\u4e00-\u9fa5]{2,4})(?:的客户|客户)?'
  field: "name"
  operator: "MATCH"
  value_type: "capture"
  value:
    group: 1
  priority: 10
```

### 2. 枚举规则

使用 `enum_ref` 和 `patterns_template` 自动展开：

```yaml
- name: "性别-枚举"
  enum_ref: "gender"
  patterns_template:
    - '{SEARCH}{enum}(?:的客户|客户)?'
  field: "gender"
  operator: "MATCH"
  value_type: "capture"
  value:
    group: 1
  priority: 10
```

**展开过程**:
- `{enum}` 被替换为 `(男|女|未知)` (捕获组)
- 生成最终 pattern: `(?:查找|...)?(?:男|女|未知)(?:的客户|客户)?`

### 3. 否定规则

支持 `negation_support: true` 的规则：

```yaml
- name: "寿险产品-未持有"
  enum_ref: "life_insurance_product"
  patterns_template:
    - '{SEARCH}{negation}{enum}(?:的客户|客户)?'
  field: "life_insurance_product"
  operator: "NOT_CONTAINS"
  value_type: "capture"
  value:
    group: 1
  priority: 10
```

**展开过程**:
- `{negation}` 被替换为 `(?:没有配置|未配置|没配置|...)`
- `{enum}` 被替换为枚举值的捕获组

---

## 占位符系统

### Pattern 变量占位符

在 `pattern_vars` 中定义，在所有 patterns 中可用：

| 占位符 | 含义 | 示例 |
|--------|------|------|
| `{SEARCH}` | 可选的查询前缀 | `(?:查找\|查询\|找\|...)?` |
| `{CW}` | 中文字符和标点 | `[，,。\.？\?...]` |

### Template 占位符

在 `patterns_template` 中使用，展开时替换：

| 占位符 | 含义 | 来源 | 示例 |
|--------|------|------|------|
| `{enum}` | 枚举值捕获组 | `enum_values[enum_ref]` | `(男\|女\|未知)` |
| `{negation}` | 否定词非捕获组 | `negation_words` | `(?:未配置\|没有\|...)` |
| `{position}` | 持有词非捕获组 | `position_words` | `(?:买了\|持有\|...)` |

### 复合规则占位符

在 `composite_rules` 的 patterns 中使用：

| 占位符 | 含义 | 示例 |
|--------|------|------|
| `【规则名】` | 引用其他规则的 patterns | `【年龄-多岁】` |

**展开过程**:
1. 找到被引用规则的所有 patterns
2. 笛卡尔积展开所有组合
3. 替换占位符后再次应用 `pattern_vars`

---

## 值转换器

在 `value.transform` 中指定，用于转换捕获的值：

### 1. `int`
将字符串转为整数。

```yaml
value:
  group: 1
  transform: "int"
```

### 2. `multiply`
将数值乘以倍数。

```yaml
value:
  group: 1
  transform: "multiply"
  multiplier: 10000  # 万 -> 元
```

### 3. `plus_range`
用于"20多岁" -> 21-29 的范围转换。

```yaml
value:
  group: 1
  transform: "plus_range"
  offset: 1
  range: 9
```

**输入**: "20"
**输出**: `RangeValue(min=21, max=29)`

### 4. `chinese_decade_plus_range`
用于中文数字"二十多岁" -> 21-29。

```yaml
value:
  group: 1
  transform: "chinese_decade_plus_range"
  offset: 1
  range: 9
```

**映射表**:
```python
{
  '十': 10, '二十': 20, '三十': 30, '四十': 40,
  '五十': 50, '六十': 60, '七十': 70, '八十': 80, '九十': 90
}
```

### 5. `exact_range`
将单个数值转为精确范围 {min: n, max: n}。

```yaml
value:
  group: 1
  transform: "exact_range"
```

### 6. `year_to_birth_range`
将出生年份转为日期范围。

```yaml
value:
  group: 1
  transform: "year_to_birth_range"
```

**输入**: "1990"
**输出**: `RangeValue(min="19900101", max="19901231")`

### 7. `ensure_suffix`
确保值有指定后缀。

```yaml
value:
  group: 1
  transform: "ensure_suffix"
  suffix: "市"
```

---

## 复合规则

### 定义

复合规则用于一次匹配多个条件，使用 `fullmatch` 模式：

```yaml
composite_rules:
  - name: "年龄多岁+婚姻"
    patterns:
      - '{SEARCH}【年龄-多岁】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的青年]{0,3})?(?:的客户|客户)?'
    priority: 20
```

### 展开过程

1. **查找引用规则**: 找到"年龄-多岁"和"婚姻状况"规则
2. **笛卡尔积**: 每个规则的所有 patterns 参与组合
3. **替换占位符**: 将 `【规则名】` 替换为实际 pattern
4. **再次展开**: 对展开后的 pattern 应用 `pattern_vars` 替换

**示例**:

假设：
- "年龄-多岁" 有 2 个 patterns
- "婚姻状况" 有 2 个 patterns

则生成 2 × 2 = 4 个展开变体。

### 捕获组偏移

复合规则中，每个子规则的捕获组需要计算偏移量：

```python
sub_rules_offsets = [
  (年龄规则, offset=0),  # 第1个捕获组
  (婚姻规则, offset=1)   # 第2个捕获组
]
```

---

## 常见问题与解决方案

### 问题 1: 复合规则中的 `{position}` 没有展开

**症状**: 展开后的 pattern 中仍包含 `{position}` 字面文本。

**原因**: `_expand_composite_refs` 在 `_expand_pattern_vars` 之后执行，但展开后的 pattern 没有再次应用变量替换。

**解决方案**: 在 `level2_enhanced_matcher.py:276-293` 中添加：

```python
# 对展开后的 pattern 再次应用 pattern_vars 替换
for var, val in self._pattern_vars.items():
    expanded = expanded.replace('{' + var + '}', val)
```

**修复日期**: 2026-03-15

---

### 问题 2: "没有配置"匹配失败

**症状**: 查询"买了金瑞人生20，但是没有配置盛世金越的客户"无法匹配。

**原因**: 否定词列表中只有"没有"，导致"没有"先被匹配，"配置"被遗漏。

**解决方案**: 在 `negation_words` 列表最前面添加"没有配置"：

```yaml
negation_words:
  - "没有配置"  # 较长的词组放在前面
  - "未配置"
  - "没配置"
  - "未购买"
  - "没有"
  - ...
```

**修复日期**: 2026-03-15

---

### 问题 3: 中文数字"二十多岁"无法匹配复合规则

**症状**: "二十多岁已婚的客户"、"刚结婚的二十多岁青年家庭"无法匹配"年龄多岁+婚姻"复合规则。

**原因**: 复合规则"年龄多岁+婚姻"只引用了"年龄-多岁"规则（支持阿拉伯数字），没有引用"年龄-中文年代几岁"规则（支持中文数字）。

**解决方案**: 添加新的复合规则"年龄中文多岁+婚姻"：

```yaml
- name: "年龄中文多岁+婚姻"
  # 二十多岁已婚的客户（中文数字）
  patterns:
    - '{SEARCH}【年龄-中文年代几岁】(?:[的、，, ]{0,3})?【婚姻状况】(?:[的青年家庭]{0,5})?(?:的客户|客户)?'
    - '{SEARCH}【婚姻状况】(?:[的、，, ]{0,3})?【年龄-中文年代几岁】(?:[的青年家庭]{0,5})?(?:的客户|客户)?'
  priority: 20
```

**说明**:
- 第一个 pattern 支持"年龄在前+婚姻在后"：二十多岁已婚的客户
- 第二个 pattern 支持"婚姻在前+年龄在后"：刚结婚的二十多岁青年家庭
- 使用 `(?:[的青年家庭]{0,5})?` 允许"青年"、"家庭"等修饰词

**修复日期**: 2026-03-15

---

### 问题 4: 动态日期范围"未来一周"和"下周"混淆

**症状**: "未来一周"和"下周"使用相同的日期范围计算。

**原因**: 两者都使用 `next_n_days` 且 `days=7`。

**解决方案**:
1. "未来一周": 从明天开始往后延7天
2. "下周": 从下周一到下周日

```python
# 未来一周
start_date = today + timedelta(days=1)
end_date = start_date + timedelta(days=n - 1)

# 下周
days_until_next_monday = (7 - today.weekday()) % 7
if days_until_next_monday == 0:
    days_until_next_monday = 7
next_monday = today + timedelta(days=days_until_next_monday)
next_sunday = next_monday + timedelta(days=6)
```

**修复日期**: 2026-03-15

---

## 最佳实践

### 1. 规则命名

- 使用清晰的描述性名称
- 格式: `字段名-操作类型[-补充说明]`
- 示例: `年龄-多岁-中文`, `寿险产品-未持有`

### 2. 优先级设置

- 基础规则: 7-10
- 复合规则: 15-25
- 越具体的规则优先级越高

### 3. Pattern 编写

- 使用 `{SEARCH}` 前缀支持可选查询词
- 使用 `(?:的客户|客户)?` 后缀支持可选结尾
- 较长的词组放在交替组前面: `(没有配置|没有)`
- 使用 `{CW}{0,2}` 允许中间有标点或空格

### 4. 枚举值管理

- 少量枚举值 (<10个): 直接在 `enum_values` 中定义
- 大量枚举值: 使用外部文件 `enum_files`
- 别名映射: 在 `value_mappings` 中定义

### 5. 值映射顺序

**重要**: 按长度降序排列，避免短串覆盖长串：

```yaml
value_mappings:
  marital_status:
    刚结婚: "已婚"  # 较长的放前面
    新婚: "已婚"
```

### 6. 否定词和持有词

按长度降序排列，确保较长的词组优先匹配：

```yaml
negation_words:
  - "没有配置"  # 3字
  - "未配置"    # 3字
  - "没配置"    # 3字
  - "没有"      # 2字
  - "没"        # 1字
```

### 7. 复合规则设计

- 只在需要同时提取多个条件时使用
- 使用 `fullmatch` 确保完整匹配
- 考虑不同的词序组合

---

## 更新日志

### 2026-03-15

**新增功能**:
1. 添加"生日-本月"规则，支持 `current_month` 动态日期范围
2. 添加"持有综拓产品类别-未持有"规则
3. 添加"年龄中文多岁+婚姻"复合规则，支持中文数字年龄（如"二十多岁"）

**Bug 修复**:
1. 修复复合规则中 `{position}` 占位符未展开的问题
2. 修复"没有配置"匹配失败问题（添加到否定词列表）
3. 修复"未来一周"和"下周"日期范围计算混淆问题
4. 修复中文数字"二十多岁"无法匹配复合规则的问题

**待实施**:
- 无

---

## 附录

### A. 操作符列表

| 操作符 | 含义 | 适用场景 |
|--------|------|----------|
| `MATCH` | 精确匹配 | 姓名、证件号 |
| `CONTAINS` | 包含 | 产品、标签 |
| `NOT_CONTAINS` | 不包含 | 未持有产品 |
| `GTE` | 大于等于 | 年龄、金额 |
| `LTE` | 小于等于 | 年龄、金额 |
| `RANGE` | 范围 | 年龄段、日期 |
| `NESTED_MATCH` | 嵌套匹配 | 家庭成员字段 |
| `ENUM_GTE` | 枚举大于等于 | 学历以上 |
| `ENUM_LTE` | 枚举小于等于 | 学历以下 |

### B. 值类型列表

| 值类型 | 含义 | 示例 |
|--------|------|------|
| `static` | 静态值 | `value: "高净值"` |
| `capture` | 捕获组 | `value: {group: 1}` |
| `range` | 范围 | `value: {min_group: 1, max_group: 2}` |
| `date_range_dynamic` | 动态日期范围 | `value: {date_range: "next_month"}` |
| `enum_gte` | 枚举大于等于 | 学历以上 |
| `enum_lte` | 枚举小于等于 | 学历以下 |

### C. 动态日期范围类型

| 类型 | 含义 | 示例 |
|------|------|------|
| `current_month` | 当前月份 | 03-01 到 03-31 |
| `next_month` | 下个月 | 04-01 到 04-30 |
| `next_n_days` | 未来N天 | 明天开始往后N天 |
| `next_week` | 下周 | 下周一到下周日 |
| `last_n_days` | 过去N天 | N天前到今天 |
| `last_year` | 去年 | 去年1月1日到12月31日 |

---

**文档结束**
