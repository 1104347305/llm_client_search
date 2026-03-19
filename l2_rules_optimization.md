# L2规则优化方案

## 分析总结

基于提供的48条查询需求，分析现有L2规则配置后，识别出以下需要优化的点：

### 1. 已覆盖的规则（无需修改）

✅ **年龄-多岁**: 规则已存在（line 634），支持"30多岁"、"40多岁"等模式
- Pattern: `(\d+)多岁` 和 `(\d+)几岁`
- Transform: `plus_range` (offset=1, range=9)
- 示例: "30多岁" → age: [31, 39]

✅ **险种-未配置**: 规则已存在（line 1189），支持"未配置重疾险"等模式
- Pattern: `{negation}{enum}(?:产品|保险)?`
- Operator: NOT_CONTAINS
- 示例: "未配置重疾险" → held_product_category NOT_CONTAINS "重疾"

✅ **客户价值简写**: value_mappings已支持（line 3395-3420）
- A1 → A1类客户
- A类 → A1类客户
- 示例: "A1有哪些" 可正确识别

✅ **小朋友识别**: value_mappings已支持（line 3520）
- 小朋友 → 子女
- 孩子 → 子女

### 2. 需要新增的规则

#### 问题1: 缺少"有娃"同义词映射

**现状**: value_mappings中有"孩子/小朋友/儿子/女儿"→"子女"，但缺少"娃"
**影响查询**:
- "有娃但没配置重疾险的客户"
- "30-40岁的已婚有娃姓女性客户"
- "35-35岁，已婚有娃的男性客户"

**解决方案**: 在value_mappings的family_members.relationship中添加"娃"→"子女"

#### 问题2: 缺少父母年龄相关规则

**现状**: 有子女年龄规则（line 1891-2013），但缺少父母年龄规则
**影响查询**:
- "父母70岁以上的客户"

**解决方案**: 新增父母年龄规则组（精确、以上、以下、范围）

#### 问题3: 缺少"家里"同义词

**现状**: 家庭成员规则使用"家庭成员|家属|成员"，但缺少"家里"
**影响查询**:
- "家里有未成年子女的客户"
- "家里有未成年子女，没有买学平险"

**解决方案**: 在家庭成员关系规则中添加"家里"作为触发词

## 具体修改方案

### 修改1: 添加"娃"同义词

**位置**: config/enhanced_rules.yaml line ~3520
**修改内容**:
```yaml
family_members.relationship:
  # 子女同义词
  孩子: "子女"
  小孩: "子女"
  小朋友: "子女"
  儿子: "子女"
  女儿: "子女"
  娃: "子女"        # 新增
  小娃: "子女"      # 新增
```

### 修改2: 新增父母年龄规则

**位置**: config/enhanced_rules.yaml line ~2014后（子女规则之后）
**新增内容**:
```yaml
# ==================== 父母年龄 (family_members.age) ====================

- name: "父母年龄-精确"
  patterns:
    - '{SEARCH}(?:父母|爸妈|父亲|母亲|爸爸|妈妈){CW}{0,2}(\d+)周?岁(?:的客户|客户)?'
    - '{SEARCH}(\d+)周?岁{CW}{0,2}(?:父母|爸妈)(?:的客户|客户)?'
  field: "family_members.age"
  operator: "RANGE"
  value_type: "capture"
  value:
    group: 1
    transform: "exact_range"
  priority: 10

- name: "父母年龄-以上"
  patterns:
    - '{SEARCH}(?:父母|爸妈|父亲|母亲|爸爸|妈妈){CW}{0,2}(\d+)岁?以上(?:的客户|客户)?'
    - '{SEARCH}(?:父母|爸妈|父亲|母亲){CW}{0,2}(?:大于|超过)(\d+)岁(?:的客户|客户)?'
    - '{SEARCH}(\d+)岁?以上{CW}{0,2}(?:父母|爸妈)(?:的客户|客户)?'
  field: "family_members.age"
  operator: "GTE"
  value_type: "capture"
  value:
    group: 1
    transform: "int"
  priority: 10

- name: "父母年龄-以下"
  patterns:
    - '{SEARCH}(?:父母|爸妈|父亲|母亲|爸爸|妈妈){CW}{0,2}(\d+)岁?以下(?:的客户|客户)?'
    - '{SEARCH}(?:父母|爸妈|父亲|母亲){CW}{0,2}(?:小于|不超过)(\d+)岁(?:的客户|客户)?'
    - '{SEARCH}(\d+)岁?以下{CW}{0,2}(?:父母|爸妈)(?:的客户|客户)?'
  field: "family_members.age"
  operator: "LTE"
  value_type: "capture"
  value:
    group: 1
    transform: "int"
  priority: 10

- name: "父母年龄-范围"
  patterns:
    - '{SEARCH}(?:父母|爸妈|父亲|母亲)(\d+)[-~到至](\d+)周?岁(?:的客户|客户)?'
    - '{SEARCH}(\d+)[-~到至](\d+)周?岁{CW}{0,2}(?:父母|爸妈)(?:的客户|客户)?'
  field: "family_members.age"
  operator: "RANGE"
  value_type: "range"
  value:
    min_group: 1
    max_group: 2
    transform: "int"
  priority: 10

# 父母年龄上下文中，附带推断关系条件（父母/爸妈/父亲/母亲 → relationship=父母）
- name: "父母-关系推断"
  patterns:
    - '{SEARCH}(父母|爸妈|父亲|母亲|爸爸|妈妈)\d+[-~到]?\d*周?岁(?:的客户|客户)?'
    - '{SEARCH}(父母|爸妈|父亲|母亲|爸爸|妈妈)(?:以上|以下|大于|小于|超过|不超过)\d+岁(?:的客户|客户)?'
  field: "family_members.relationship"
  operator: "CONTAINS"
  value_type: "static"
  value: "父母"
  priority: 9
```

### 修改3: 优化家庭成员关系规则，支持"家里"

**位置**: config/enhanced_rules.yaml line 1852-1875
**修改内容**:
```yaml
- name: "家庭成员关系-有"
  enum_ref: "family_members.relationship"
  patterns_template:
    - '{SEARCH}(?<![没无])有?{enum}(?:的客户|客户)?'
    # 支持修饰词在中间：有未成年子女、有年迈父母
    - '{SEARCH}(?<![没无])有?[\u4e00-\u9fa5]{0,2}{enum}(?:的客户|客户)?'
    # 新增：支持"家里有"
    - '{SEARCH}家里(?<![没无])有?[\u4e00-\u9fa5]{0,2}{enum}(?:的客户|客户)?'
  field: "family_members.relationship"
  operator: "CONTAINS"
  value_type: "capture"
  value:
    group: 1
  priority: 10

- name: "家庭成员关系-无"
  enum_ref: "family_members.relationship"
  patterns_template:
    - '{SEARCH}(?:无|没有){enum}(?:的客户|客户)?'
    - '{SEARCH}(?:无|没有)[\u4e00-\u9fa5]{0,2}{enum}(?:的客户|客户)?'
    # 新增：支持"家里没有"
    - '{SEARCH}家里(?:无|没有)[\u4e00-\u9fa5]{0,2}{enum}(?:的客户|客户)?'
  field: "family_members.relationship"
  operator: "NOT_CONTAINS"
  value_type: "capture"
  value:
    group: 1
  priority: 10
```

## 测试用例

修改后应能正确处理以下查询：

1. ✅ "35岁有小朋友友还没配置重疾险的客户" - 已支持
2. ✅ "有娃但没配置重疾险的客户" - 修改1后支持
3. ✅ "父母70岁以上的客户" - 修改2后支持
4. ✅ "家里有未成年子女的客户" - 修改3后支持
5. ✅ "家里有未成年子女，没有买学平险" - 修改3后支持
6. ✅ "30多岁客户" - 已支持
7. ✅ "未配置重疾险的客户" - 已支持
8. ✅ "A1有哪些" - 已支持

## 优先级建议

1. **高优先级**: 修改1（添加"娃"同义词）- 影响3条查询，修改简单
2. **高优先级**: 修改2（父母年龄规则）- 影响1条查询，但是新功能
3. **中优先级**: 修改3（支持"家里"）- 影响2条查询，增强语义覆盖

## 注意事项

1. 所有修改都遵循现有规则的设计模式
2. 父母年龄规则与子女年龄规则结构一致
3. 使用value_mappings预处理，确保"父亲/母亲/爸爸/妈妈"都映射到"父母"
4. 优先级设置与同类规则保持一致
5. 所有pattern都包含`{SEARCH}`前缀和`(?:的客户|客户)?`后缀
