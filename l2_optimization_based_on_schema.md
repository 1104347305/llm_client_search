# 基于客户信息表格定义的L2规则优化建议

## 字段枚举值（来自官方文档）

### held_product_category（持有产品类别）
- 意外伤害保险
- 医疗保险
- 定期寿险
- 两全保险
- 年金保险
- 终身寿险

### life_liability_type（持有寿险产品责任类型）
- 寿险
- 重疾
- 意外
- 医疗
- 财富
- 养老

### life_design_type（持有寿险产品设计类型）
- 分红
- 投连
- 万能
- 普通
- 其他

## 用户查询与字段映射

### "重疾险"应该匹配哪个字段？
根据表格定义：
- ❌ held_product_category：没有"重疾险"
- ✅ life_liability_type：有"重疾"

**结论**：用户说"重疾险"时，应该匹配`life_liability_type`的"重疾"

### "万能险"应该匹配哪个字段？
根据表格定义：
- ❌ held_product_category：没有"万能险"
- ✅ life_design_type：有"万能"

**结论**：用户说"万能险"时，应该匹配`life_design_type`的"万能"

### "意外险"应该匹配哪个字段？
根据表格定义：
- ✅ held_product_category：有"意外伤害保险"
- ✅ life_liability_type：有"意外"

**结论**：两个字段都可以，但held_product_category更精确

## 优化策略

### 1. 扩展规则patterns，支持常见查询模式

#### 为所有枚举规则添加常见结尾：
- "名单"
- "有哪些"
- "都有谁"
- "的人"

#### 示例：
```yaml
- name: "寿险责任类型-持有"
  patterns_template:
    - '{SEARCH}{enum}(?:责任|产品|险|保险)?(?:的客户|客户)?'
    - '{SEARCH}{enum}(?:责任|产品|险|保险)?名单'
    - '{SEARCH}{enum}(?:责任|产品|险|保险)?有哪些'
```

### 2. 调整value_mappings

#### 保留必要的映射，移除破坏性映射：

**保留**（这些是同义词归一化）：
```yaml
held_product_category:
  百万医疗保险: "医疗保险"
  百万医疗: "医疗保险"
```

**移除**（这些会破坏匹配）：
```yaml
# 移除这些，因为会将"意外险"变成"意外伤害保险"，导致无法匹配
# held_product_category:
#   意外险: "意外伤害保险"
#   医疗险: "医疗保险"
#   年金险: "年金保险"
```

### 3. 在枚举中添加常见简称

虽然官方定义没有简称，但为了匹配用户查询，需要在枚举中添加：

```yaml
held_product_category:
  - "意外伤害保险"
  - "意外险"          # 添加简称
  - "医疗保险"
  - "医疗险"          # 添加简称
  - "百万医疗"        # 添加简称
  - "定期寿险"
  - "定寿"            # 添加简称
  - "两全保险"
  - "两全险"          # 添加简称
  - "年金保险"
  - "年金险"          # 添加简称
  - "终身寿险"
  - "终身寿"          # 添加简称

life_liability_type:
  - "寿险"
  - "重疾"
  - "重疾险"          # 添加简称
  - "意外"
  - "意外险"          # 添加简称
  - "医疗"
  - "医疗险"          # 添加简称
  - "财富"
  - "养老"
  - "养老险"          # 添加简称

life_design_type:
  - "分红"
  - "分红险"          # 添加简称
  - "投连"
  - "投连险"          # 添加简称
  - "万能"
  - "万能险"          # 添加简称
  - "普通"
  - "普通险"          # 添加简称
  - "其他"
```

## 测试用例映射

基于表格定义，这些查询应该这样匹配：

1. "未配置重疾险的客户" → life_liability_type NOT_CONTAINS "重疾"
2. "所有万能险客户名单" → life_design_type CONTAINS "万能"
3. "给我看看意外险名单" → held_product_category CONTAINS "意外伤害保险" 或 life_liability_type CONTAINS "意外"
4. "未配置养老保险的人员名单" → life_liability_type NOT_CONTAINS "养老"
5. "给我看看40岁低温分红险客户" → age=40 + customer_temperature="低温" + life_design_type CONTAINS "分红"

## 立即执行的修改

1. 扩展held_product_category枚举（添加简称）
2. 扩展life_liability_type枚举（添加简称）
3. 扩展life_design_type枚举（添加简称）
4. 为所有枚举规则添加"名单"、"有哪些"等pattern
5. 注释掉held_product_category的破坏性value_mappings
