"""
字段映射和元数据定义
"""

# 字段类型定义（完整字段列表）
FIELD_TYPES = {
    # 基础信息
    "name": "text",
    "mobile_phone": "text",
    "gender": "enum",
    "client_birth": "date",
    "client_birth_month_and_day": "text",
    "age": "number",
    "education": "enum",
    "marital_status": "enum",
    "customer_id": "text",
    "customer_added_date": "date",
    "customer_value": "enum",
    "customer_temperature": "enum",
    "customer_segment_tag": "enum",
    "operation_stage": "enum",
    "stock_customer_type": "enum",
    "wechat_nickname": "text",
    "email": "text",
    "nationality": "text",
    "registered_residence": "text",
    "contact_address": "text",
    "home_address": "text",
    "height": "text",
    "weight": "text",
    "occupation": "text",
    "years_in_service": "text",
    "employer": "text",
    "work_phone": "text",
    "department": "text",
    "job_position": "text",
    "company_address": "text",
    "annual_income": "number",
    "household_income": "number",
    "real_estate_status": "enum",
    "asset_scale": "enum",
    "vehicle_model": "text",
    "vehicle_plate_number": "text",
    "vehicle_purchase_price": "enum",
    "investable_assets": "enum",
    "prospect_source": "enum",

    # 保险产品相关
    "life_insurance_product": "text",
    "held_product_type": "enum",
    "held_product_category": "enum",
    "property_insurance_product": "text",
    "pension_insurance_product": "text",
    "health_insurance": "text",
    "life_liability_type": "enum",
    "life_design_type": "enum",
    "target_purchase_category": "enum",
    "annual_premium": "number",
    "total_coverage": "text",
    "latest_underwriting_time": "enum",
    "is_survival_gold_claimed": "enum",
    "is_payment_matured": "enum",
    "policy_anniversary": "date",
    "held_cross_sell_category": "text",
    "is_cross_sell_claim": "text",
    "policy_expiry_date": "enum",
    "valid_short_term_policy": "text",
    "is_life_insured": "enum",

    # VIP 和权益相关
    "life_insurance_vip": "enum",
    "pingan_vip": "enum",
    "home_care_level": "enum",
    "health_care_level": "enum",
    "anyouhu_level": "enum",
    "zhenxiang_family_level": "enum",

    # 家庭成员信息
    "family_members.relationship": "nested",
    "family_members.name": "nested",
    "family_members.birth_date": "nested",
    "family_members.age": "nested",
    "family_members.mobile": "nested",

    # 证件信息
    "certificates.id_type": "nested",
    "certificates.id_number": "nested",

    # 保单信息
    "policies.product_name": "nested",
    "policies.policy_id": "nested",
    "policies.effective_date": "nested",
    "policies.status": "nested",
    "policies.period_premium": "nested",
    "policies.due_date": "nested",
    "policies.underwriting_conclusion": "nested",
    "policies.free_look_expiry": "nested",
    "policies.coverage_details": "nested",
    "policies.applicant_name": "nested",
    "policies.applicant_mobile": "nested",
    "policies.applicant_age": "nested",
    "policies.insured_name": "nested",
    "policies.insured_mobile": "nested",
    "policies.insured_age": "nested",
    "policies.beneficiary_name": "nested",
    "policies.beneficiary_mobile": "nested",
    "policies.beneficiary_age": "nested",
    "policies.survival_total_amount": "nested",
    "policies.survival_claimed_amount": "nested",
    "policies.survival_unclaimed_amount": "nested",
    "policies.universal_acct_transfer": "nested",
    "policies.survival_interest_total": "nested",
    "policies.claim_records": "nested",

    # 权益信息
    "benefits.member_info": "nested",
    "benefits.pingan_info": "nested",
}

# 中文字段映射到英文字段
CHINESE_TO_ENGLISH = {
    "姓名": "name",
    "手机号": "mobile_phone",
    "性别": "gender",
    "年龄": "age",
    "学历": "education",
    "婚姻状况": "marital_status",
    "客户号": "customer_id",
    "客户价值": "customer_value",
    "寿险产品": "life_insurance_product",
    "持有产品类别": "held_product_category",
    "年缴保费": "annual_premium",
    "总保额": "total_coverage",
    "联系地址": "contact_address",
    "家庭地址": "home_address",
    "年收入": "annual_income",
    "家庭收入": "household_income",
    "保单号": "policies.policy_id",
    "身份证号": "certificates.id_number",
    "存量客户类型": "stock_customer_type",
}

# 险种关键词映射
INSURANCE_TYPE_MAPPING = {
    "养老险": "养老保险",
    "养老保险": "养老保险",
    "重疾险": "重疾",
    "重疾": "重疾",
    "医疗险": "医疗保险",
    "医疗保险": "医疗保险",
    "百万医疗": "百万医疗",
    "意外险": "意外伤害保险",
    "意外伤害保险": "意外伤害保险",
    "年金险": "年金保险",
    "年金保险": "年金保险",
    "万能险": "万能",
    "万能": "万能",
}

# 产品名称关键词
PRODUCT_KEYWORDS = [
    "平安福", "e生保", "天年", "金越", "守护百分百",
    "盛世金越", "合家欢", "安佑福", "颐享世家"
]

# 年龄段关键词
AGE_KEYWORDS = {
    "小朋友": {"min": 0, "max": 12},
    "子女": {"min": 0, "max": 18},
    "青年": {"min": 18, "max": 35},
    "中年": {"min": 35, "max": 55},
    "老年": {"min": 55, "max": 120},
}

# 否定词
NEGATION_WORDS = ["没", "未", "无", "不", "缺", "没有", "未配置", "没买", "没购买"]

# 逻辑词
LOGIC_WORDS = {
    "AND": ["并且", "而且", "同时", "且", "和"],
    "OR": ["或者", "或", "要么"],
}
