"""
字段映射和元数据定义
"""

# 字段类型定义（以Excel客户表格定义英文字段名为准）
FIELD_TYPES = {
    # 客户基础信息
    "clientName": "text",
    "clientMobile": "text",
    "clientSex": "enum",
    "clientBirthday": "date",
    "birthdayMd": "text",
    "clientAge": "number",
    "marriSts": "enum",
    "education": "enum",
    "profName": "text",
    "carBrand": "text",
    "carNumber": "text",
    "assetsCondition": "enum",

    # 客户证件信息
    "idType": "enum",
    "idNo": "text",
    "idValidDate": "date",

    # 客户标识
    "clientNo": "text",

    # 客户分类标签
    "newValueLabel": "enum",
    "clientTemperature": "enum",
    "clientGroupLabel": "enum",
    "vipType": "enum",
    "orphanType": "enum",
    "trusteeshipFlag": "enum",

    # 持有产品类型
    "productCode": "text",
    "pType": "enum",
    "pcCategory": "enum",
    "isBuyPregnancyCar": "enum",
    "gProductCode": "text",
    "hProductCode": "text",

    # 长险保单事件
    "amPremSeg": "number",
    "insnoSumInsSeq": "number",
    "effAppEndDate": "date",

    # 短险保单事件
    "effAnniversaryDate": "date",
    "agentPerspProductType": "enum",
    "occurPassPayRegst": "enum",
    "validSinsMatuDate": "date",
    "validSinsPol": "enum",

    # 会员等级
    "jujiaClientGrade": "enum",
    "kangyangClientGrade": "enum",
    "zhenxiangRunEquityGrade": "enum",
    "zxjyEquityGrade": "enum",

    # 客户家庭成员（嵌套）
    "familyRelation": "nested",
    "familyClientName": "nested",
    "familyClientSex": "nested",
    "familyClientBirthday": "nested",

    # 保单信息（嵌套）
    "policyNo": "nested",

    # 保单内嵌套字段（投被保人等，字段名保持原样）
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

    # 权益信息（嵌套）
    "benefits.member_info": "nested",
    "benefits.pingan_info": "nested",
}

# 中文字段映射到英文字段
CHINESE_TO_ENGLISH = {
    "姓名": "clientName",
    "手机号": "clientMobile",
    "性别": "clientSex",
    "年龄": "clientAge",
    "学历": "education",
    "婚姻状况": "marriSts",
    "客户号": "clientNo",
    "客户价值": "newValueLabel",
    "寿险产品": "productCode",
    "持有产品类别": "pcCategory",
    "年缴保费": "amPremSeg",
    "保单号": "policyNo",
    "身份证号": "idNo",
    "存量客户类型": "orphanType",
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
