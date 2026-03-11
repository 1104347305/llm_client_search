"""
Level 1: 规则引擎 - 基于正则表达式的确定性实体提取
"""
import re
import jieba
import jieba.posseg as pseg
from typing import List, Tuple
from loguru import logger
from app.models.schemas import Condition, Operator


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

        # 初始化 Jieba（静默模式）
        jieba.setLogLevel(jieba.logging.INFO)

        # 添加常见测试姓名到词典
        common_names = ['张三', '李四', '王五', '赵六', '刘德华', '周杰伦', '马云', '张伟', '李娜']
        for name in common_names:
            jieba.add_word(name, freq=1000, tag='nr')

        logger.info("Level1RuleEngine initialized with Jieba")

    def _extract_names_with_jieba(self, query: str) -> List[str]:
        """使用 Jieba 提取人名"""
        names = []
        words = list(pseg.cut(query))
        if len(words) == 1:
            for word, flag in words:
                # nr: 人名, nrt: 人名(音译)
                if flag in ['nr', 'nrt', 'nrfg'] and len(word) >= 2 and len(word) <= 3:
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
        remaining_text = query
        extracted_parts = []
        extracted_positions = set()

        # 先提取客户号（C + 16位数字，优先级最高）
        customer_matches = self.customer_pattern.finditer(query)
        for match in customer_matches:
            customer_id = match.group(0)
            conditions.append(Condition(
                field="customer_id",
                operator=Operator.MATCH,
                value=customer_id
            ))
            extracted_parts.append(customer_id)
            extracted_positions.update(range(match.start(), match.end()))
            logger.info(f"Extracted customer ID: {customer_id}")

        # 提取保单号（P + 15位数字）
        policy_matches = self.policy_pattern.finditer(query)
        for match in policy_matches:
            # 检查是否与客户号重叠
            policy_range = set(range(match.start(), match.end()))
            if not policy_range & extracted_positions:
                policy_id = match.group(0)
                conditions.append(Condition(
                    field="policies.policy_id",
                    operator=Operator.NESTED_MATCH,
                    value=policy_id
                ))
                extracted_parts.append(policy_id)
                extracted_positions.update(range(match.start(), match.end()))
                logger.info(f"Extracted policy ID: {policy_id}")

        # 提取身份证号（18位）
        id_matches = self.id_card_pattern.finditer(query)
        for match in id_matches:
            # 检查是否与保单号重叠
            id_range = set(range(match.start(), match.end()))
            if not id_range & extracted_positions:
                id_card = match.group(0)
                conditions.append(Condition(
                    field="certificates.id_number",
                    operator=Operator.NESTED_MATCH,
                    value=id_card
                ))
                extracted_parts.append(id_card)
                extracted_positions.update(range(match.start(), match.end()))
                logger.info(f"Extracted ID card: {id_card}")

        # 提取手机号（11位，排除已提取的身份证号区域）
        phone_matches = self.phone_pattern.finditer(query)
        for match in phone_matches:
            # 检查是否与身份证号重叠
            phone_range = set(range(match.start(), match.end()))
            if not phone_range & extracted_positions:
                phone = match.group(0)
                conditions.append(Condition(
                    field="mobile_phone",
                    operator=Operator.MATCH,
                    value=phone
                ))
                extracted_parts.append(phone)
                logger.info(f"Extracted phone: {phone}")

        # 使用 Jieba 提取人名
        jieba_names = self._extract_names_with_jieba(query)
        for name in jieba_names:
            # 排除"孤儿"、"青年"、"中年"、"老年"、"养老"等非真实姓名的词
            if name not in ['孤儿', '青年', '中年', '老年', '养老']:
                conditions.append(Condition(
                    field="name",
                    operator=Operator.MATCH,
                    value=name
                ))
                # 尝试从查询中移除这个名字
                if name in query:
                    extracted_parts.append(name)
                logger.info(f"Extracted name via Jieba: {name}")

        # 移除已提取的部分
        for part in extracted_parts:
            remaining_text = remaining_text.replace(part, "")

        # 清理多余空格
        remaining_text = re.sub(r'\s+', ' ', remaining_text).strip()

        # 判断是否有剩余文本
        has_residual = len(remaining_text) > 0

        logger.info(f"Level 1 extracted {len(conditions)} conditions, residual: {has_residual}")
        return conditions, remaining_text, has_residual
