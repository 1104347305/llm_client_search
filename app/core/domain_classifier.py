"""
领域分类器 - 使用轻量级 LLM 进行领域分类
"""
from typing import List, Set
from loguru import logger
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from config.settings import settings
from app.models.field_mapping import FIELD_TYPES


class DomainClassifier:
    """领域分类器 - 4大类"""

    # 4大领域定义
    DOMAINS = {
        "客户基本信息": [
            "name", "mobile_phone", "gender", "client_birth", "client_birth_month_and_day",
            "age", "education", "marital_status", "customer_id", "customer_added_date",
            "customer_value", "customer_temperature", "customer_segment_tag", "operation_stage",
            "stock_customer_type", "wechat_nickname", "email", "nationality", "registered_residence",
            "contact_address", "home_address", "height", "weight", "occupation", "years_in_service",
            "employer", "work_phone", "department", "job_position", "company_address",
            "annual_income", "household_income", "real_estate_status", "asset_scale",
            "vehicle_model", "vehicle_plate_number", "vehicle_purchase_price", "investable_assets",
            "prospect_source"
        ],
        "家庭成员信息": [
            "family_members.relationship", "family_members.name", "family_members.birth_date",
            "family_members.age", "family_members.mobile"
        ],
        "保单信息": [
            "life_insurance_product", "held_product_type", "held_product_category",
            "property_insurance_product", "pension_insurance_product", "health_insurance",
            "life_liability_type", "life_design_type", "target_purchase_category",
            "annual_premium", "total_coverage", "latest_underwriting_time",
            "is_survival_gold_claimed", "is_payment_matured", "policy_anniversary",
            "held_cross_sell_category", "is_cross_sell_claim", "policy_expiry_date",
            "valid_short_term_policy", "is_life_insured",
            "certificates.id_type", "certificates.id_number",
            "policies.product_name", "policies.policy_id", "policies.effective_date",
            "policies.status", "policies.period_premium", "policies.due_date",
            "policies.underwriting_conclusion", "policies.free_look_expiry",
            "policies.coverage_details", "policies.applicant_name", "policies.applicant_mobile",
            "policies.insured_name", "policies.insured_mobile", "policies.beneficiary_name",
            "policies.beneficiary_mobile", "policies.survival_total_amount",
            "policies.survival_claimed_amount", "policies.survival_unclaimed_amount",
            "policies.universal_acct_transfer", "policies.survival_interest_total",
            "policies.claim_records"
        ],
        "客户权益": [
            "life_insurance_vip", "pingan_vip", "home_care_level", "health_care_level",
            "anyouhu_level", "zhenxiang_family_level",
            "benefits.member_info", "benefits.pingan_info"
        ]
    }

    def __init__(self):
        """初始化领域分类器"""
        self.agent = Agent(
            model=OpenAIChat(
                id="qwen-turbo",
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
            ),
            markdown=False,
        )
        logger.info("Domain classifier initialized with qwen-turbo")

    async def classify(self, query: str) -> List[str]:
        """
        分类查询涉及的领域

        Args:
            query: 用户查询

        Returns:
            相关领域列表
        """
        prompt = f"""你是一个客户搜索系统的领域分类器。请分析用户查询涉及哪些领域。

可选领域：
1. 客户基本信息 - 包括姓名、年龄、性别、学历、婚姻、职业、收入、资产等
2. 家庭成员信息 - 包括家庭成员关系、姓名、年龄等
3. 保单信息 - 包括保险产品、保单、保费、保额、险种等
4. 客户权益 - 包括VIP等级、会员权益等

用户查询：{query}

请直接返回相关领域名称，多个领域用逗号分隔，不要有其他内容。
例如：客户基本信息,保单信息
"""

        try:
            import asyncio
            result: RunOutput = await asyncio.to_thread(self.agent.run, prompt)
            response = result.content.strip()

            # 解析领域
            domains = []
            for domain in self.DOMAINS.keys():
                if domain in response:
                    domains.append(domain)

            # 如果没有匹配到任何领域，返回所有领域
            if not domains:
                logger.warning(f"No domain matched for query: {query}, using all domains")
                domains = list(self.DOMAINS.keys())

            logger.info(f"Query classified to domains: {domains}")
            return domains

        except Exception as e:
            logger.error(f"Domain classification failed: {e}")
            # 失败时返回所有领域
            return list(self.DOMAINS.keys())

    def get_fields_for_domains(self, domains: List[str]) -> Set[str]:
        """
        获取指定领域的所有字段

        Args:
            domains: 领域列表

        Returns:
            字段集合
        """
        fields = set()
        for domain in domains:
            if domain in self.DOMAINS:
                fields.update(self.DOMAINS[domain])

        logger.info(f"Retrieved {len(fields)} fields for domains: {domains}")
        return fields
