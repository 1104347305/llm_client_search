"""
Level 1: 规则引擎 - 基于正则表达式的确定性实体提取
"""
import re
import jieba
import jieba.posseg as pseg
from typing import List, Tuple
from loguru import logger
from models.schemas import Condition, Operator


class Level1RuleEngine:
    """规则引擎 - 提取确定性实体"""

    def __init__(self):
        """初始化规则引擎"""
        # 手机号正则
        self.phone_pattern = re.compile(r'1[3-9]\d{9}')
        # 身份证号正则
        self.id_card_pattern = re.compile(r'\d{17}[\dXx]')
        # 保单号正则 (P + 15位数字，如 P966073446746215)
        self.policy_pattern = re.compile(r'P\d{15}')
        # 客户号正则 (C + 15位数字，如 C335906420260306)
        self.customer_pattern = re.compile(r'C\d{15}')
        # 姓名正则 (2-4个中文字符)
        self.name_pattern = re.compile(r'[\u4e00-\u9fa5]{2,4}')
        self._last_matched_patterns = []

        logger.info("Level1RuleEngine initialized with Jieba")

    def _extract_names_with_jieba(self, query: str) -> List[str]:
        """使用 Jieba 提取人名"""
        names = []
        words = list(pseg.cut(query))
        if len(words) == 1:
            for word, flag in words:
                # nr: 人名, nrt: 人名(音译)
                if flag in ['nr', 'nrt', 'nrfg'] and len(word) >= 2 and len(word) <= 4:
                    names.append(word)
                    logger.debug(f"Jieba extracted name: {word} (flag: {flag})")
        return names

    async def extract(self, query: str) -> Tuple[List[Condition], str, bool]:
        """
        提取确定性实体（异步版本）

        Args:
            query: 用户查询

        Returns:
            (conditions, remaining_text, has_residual)
        """
        conditions = []
        extracted_positions = set()
        self._last_matched_patterns = []

        # 先提取客户号（C + 16位数字，优先级最高）
        customer_matches = self.customer_pattern.fullmatch(query)
        if customer_matches:
            customer_id = customer_matches.group()
            self._last_matched_patterns.append({
                "rule_name": "客户号",
                "pattern": self.customer_pattern.pattern,
                "matched_text": customer_id,
                "match_type": "regex",
            })
            conditions.append(Condition(
                field="clientNo",
                operator=Operator.MATCH,
                value=customer_id
            ))
            logger.info(f"Extracted customer ID: {customer_id}")

        # 提取保单号（P + 15位数字）
        policy_matches = self.policy_pattern.fullmatch(query)
        if policy_matches:
            policy_id = policy_matches.group()
            self._last_matched_patterns.append({
                "rule_name": "保单号",
                "pattern": self.policy_pattern.pattern,
                "matched_text": policy_id,
                "match_type": "regex",
            })
            conditions.append(Condition(
                field="policyNo",
                operator=Operator.NESTED_MATCH,
                value=policy_id
            ))
            logger.info(f"Extracted policy ID: {policy_id}")

        # 提取身份证号（18位）
        id_matches = self.id_card_pattern.fullmatch(query)
        if id_matches:
            id_number = id_matches.group()
            self._last_matched_patterns.append({
                "rule_name": "身份证号",
                "pattern": self.id_card_pattern.pattern,
                "matched_text": id_number,
                "match_type": "regex",
            })
            conditions.append(Condition(
                field="idNo",
                operator=Operator.NESTED_MATCH,
                value=id_number
            ))
            logger.info(f"Extracted ID card: {id_number}")

        # 提取手机号（11位，排除已提取的身份证号区域）
        phone_matches = self.phone_pattern.fullmatch(query)
        if phone_matches:
            mobile_phone = phone_matches.group()
            self._last_matched_patterns.append({
                "rule_name": "手机号",
                "pattern": self.phone_pattern.pattern,
                "matched_text": mobile_phone,
                "match_type": "regex",
            })
            conditions.append(Condition(
                field="clientMobile",
                operator=Operator.MATCH,
                value=mobile_phone
            ))
            logger.info(f"Extracted phone: {mobile_phone}")

        # 使用 Jieba 提取人名
        jieba_names = self._extract_names_with_jieba(query)
        for name in jieba_names:
            self._last_matched_patterns.append({
                "rule_name": "人名",
                "pattern": "jieba:nr",
                "matched_text": name,
                "match_type": "jieba",
            })
            conditions.append(Condition(
                field="clientName",
                operator=Operator.MATCH,
                value=name
            ))
            logger.info(f"Extracted name via Jieba: {name}")

        logger.info(f"Level 1 extracted {conditions} conditions")
        return conditions

if __name__ == '__main__':
    import asyncio

    level1 = Level1RuleEngine()
    questions = [

    ]
    for question in questions:
        conditions = asyncio.run(level1.extract())
        for condition in conditions:
            print(dict(condition))
