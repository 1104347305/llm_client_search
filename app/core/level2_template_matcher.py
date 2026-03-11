"""
Level 2: 模板匹配器 - 基于配置的字段提取
"""
import re
import yaml
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path
from loguru import logger
from app.models.schemas import Condition, Operator, RangeValue
from app.models.field_mapping import INSURANCE_TYPE_MAPPING, NEGATION_WORDS


def chinese_to_arabic(chinese_num: str) -> int:
    """将中文数字转换为阿拉伯数字"""
    # 简单映射表
    simple_map = {
        '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
        '十': 10, '百': 100, '千': 1000
    }

    # 处理特殊情况
    if chinese_num in simple_map:
        return simple_map[chinese_num]

    # 处理"二十"、"三十"等
    if len(chinese_num) == 2 and chinese_num[1] == '十':
        return simple_map.get(chinese_num[0], 0) * 10

    # 处理"十几"
    if chinese_num == '十几':
        return 15

    # 处理复杂数字（如"二十三"、"一百二十"）
    result = 0
    temp = 0
    for char in chinese_num:
        if char in ['十', '百', '千']:
            if temp == 0:
                temp = 1
            result += temp * simple_map[char]
            temp = 0
        elif char in simple_map:
            temp = simple_map[char]

    result += temp
    return result if result > 0 else int(chinese_num) if chinese_num.isdigit() else 0


class Level2TemplateMatcher:
    """模板匹配器 - 可配置的字段提取"""

    def __init__(self, config_path: str = "config/template_rules.yaml"):
        """初始化模板匹配器"""
        logger.debug(f"Initializing Level2TemplateMatcher with config_path: {config_path}")

        # 如果是相对路径，尝试从多个位置查找
        if not Path(config_path).is_absolute():
            # 尝试1: 相对于当前工作目录
            path1 = Path(config_path)
            # 尝试2: 相对于此文件所在目录的项目根目录
            path2 = Path(__file__).parent.parent.parent / config_path

            if path1.exists():
                self.config_path = path1
                logger.debug(f"Using config from current directory: {path1.absolute()}")
            elif path2.exists():
                self.config_path = path2
                logger.debug(f"Using config from project root: {path2.absolute()}")
            else:
                self.config_path = path1  # 默认使用第一个
                logger.warning(f"Config file not found in either location. Tried: {path1.absolute()}, {path2.absolute()}")
        else:
            self.config_path = Path(config_path)

        self.rules = []
        self.negation_words = NEGATION_WORDS
        self.insurance_mapping = {}
        self.education_age_mapping = {}
        logger.debug(f"About to call load_config(), config_path exists: {self.config_path.exists()}")
        self.load_config()
        logger.debug(f"After load_config(), rules count: {len(self.rules)}")

    def get_rules_count(self) -> int:
        """获取规则数量（用于调试）"""
        return len(self.rules)

    def debug_info(self) -> dict:
        """获取调试信息"""
        return {
            "config_path": str(self.config_path.absolute()),
            "config_exists": self.config_path.exists(),
            "rules_count": len(self.rules),
            "rules_loaded": self.rules is not None and len(self.rules) > 0,
            "first_rule": self.rules[0] if self.rules else None
        }

    def load_config(self):
        """加载配置文件"""
        try:
            if not self.config_path.exists():
                logger.error(f"Config file not found: {self.config_path.absolute()}")
                self.rules = []
                return

            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config is None:
                    logger.error("Config file is empty or invalid YAML")
                    self.rules = []
                    return

                self.rules = config.get('custom_rules', [])
                self.negation_words = config.get('negation_words', NEGATION_WORDS)
                self.insurance_mapping = config.get('insurance_mapping', {})
                self.education_age_mapping = config.get('education_age_mapping', {})
            logger.info(f"Loaded {len(self.rules)} template rules from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to load template rules: {e}")
            self.rules = []

    async def match(self, query: str) -> Tuple[List[Condition], str, bool]:
        """
        模板匹配 - 支持从配置中读取 operator 和 value

        Args:
            query: 用户查询

        Returns:
            (conditions, remaining_text, has_residual)
        """
        # 第一步：收集所有可能的匹配
        all_matches = []

        for rule in self.rules:
            field = rule.get('field')
            patterns = rule.get('patterns', [])
            priority = rule.get('priority', 0)

            for pattern_str in patterns:
                try:
                    pattern = re.compile(pattern_str)
                    matches = pattern.finditer(query)

                    for match in matches:
                        all_matches.append({
                            'rule': rule,
                            'match': match,
                            'start': match.start(),
                            'end': match.end(),
                            'length': match.end() - match.start(),
                            'priority': priority
                        })

                except re.error as e:
                    logger.warning(f"Invalid regex pattern: {pattern_str}, error: {e}")

        # 第二步：按优先级（降序）和匹配长度（降序）排序
        all_matches.sort(key=lambda x: (-x['priority'], -x['length'], x['start']))

        # 第三步：选择不冲突的匹配
        conditions = []
        extracted_positions = set()

        for match_info in all_matches:
            match_range = range(match_info['start'], match_info['end'])

            # 检查是否与已提取的位置重叠
            if any(pos in extracted_positions for pos in match_range):
                continue

            # 构建条件
            condition = self._build_condition_from_rule(
                match_info['rule'],
                match_info['match'],
                query
            )
            if condition:
                conditions.append(condition)
                extracted_positions.update(match_range)

        # 构建剩余文本（移除已提取的部分）
        remaining_chars = []
        for i, char in enumerate(query):
            if i not in extracted_positions:
                remaining_chars.append(char)
        remaining_text = ''.join(remaining_chars)

        # 清理多余空格
        remaining_text = re.sub(r'\s+', ' ', remaining_text).strip()

        has_residual = len(remaining_text) > 0

        logger.info(f"Level 2 matched {len(conditions)} conditions, residual: {has_residual}")
        return conditions, remaining_text, has_residual

    def _build_condition_from_rule(self, rule: Dict, match: re.Match, query: str) -> Optional[Condition]:
        """
        从规则配置构建条件

        优先级：
        1. 如果规则中配置了 operator，直接使用配置化方式
        2. 否则使用原有的字段特定处理逻辑
        """
        field = rule.get('field')

        # 检查规则是否配置了 operator（配置化规则）
        if 'operator' in rule:
            return self._build_from_config(rule, match, query)

        # 否则使用原有的处理逻辑
        return self._process_match(field, match, query)

    def _build_from_config(self, rule: Dict, match: re.Match, query: str) -> Optional[Condition]:
        """从配置直接构建条件"""
        field = rule.get('field')
        operator_str = rule.get('operator')
        value_config = rule.get('value')
        value_type = rule.get('value_type', 'static')

        # 映射操作符字符串到枚举
        operator_map = {
            "MATCH": Operator.MATCH,
            "GTE": Operator.GTE,
            "LTE": Operator.LTE,
            "RANGE": Operator.RANGE,
            "CONTAINS": Operator.CONTAINS,
            "NOT_CONTAINS": Operator.NOT_CONTAINS,
            "NESTED_MATCH": Operator.NESTED_MATCH,
        }
        operator = operator_map.get(operator_str, Operator.MATCH)

        # 根据 value_type 处理值
        value = None
        if value_type == 'capture':
            # 从正则捕获组提取值
            try:
                if match.groups():
                    value = match.group(1)
                else:
                    value = match.group(0)
                if not value:
                    return None
            except IndexError:
                return None
        elif isinstance(value_config, dict) and 'min' in value_config and 'max' in value_config:
            # 范围值
            value = RangeValue(min=value_config['min'], max=value_config['max'])
        else:
            # 静态值
            value = value_config

        if value is None:
            return None

        return Condition(field=field, operator=operator, value=value)

    def _process_match(self, field: str, match: re.Match, query: str) -> Optional[Condition]:
        """处理匹配结果"""
        # 优先检查规则中是否直接配置了 operator 和 value
        rule = self._find_rule_by_field_and_pattern(field, match.re.pattern)

        if rule:
            # 如果规则中直接配置了 operator 和 value，直接使用
            if 'operator' in rule and 'value' in rule:
                return self._build_condition_from_rule(rule, match, query)

        # 否则使用原有的处理逻辑
        if field == "age":
            return self._process_age(match, query)
        elif field == "insurance_type" or field == "held_product_category":
            return self._process_insurance_type(match, query)
        elif field == "marital_status":
            return self._process_marital_status(match)
        elif field == "children":
            return self._process_children(match)
        elif field == "premium" or field == "annual_premium":
            return self._process_premium(match)
        elif field == "income" or field == "annual_income" or field == "household_income":
            return self._process_income(match)
        elif field == "product" or field == "life_insurance_product":
            return self._process_product(match, query)
        else:
            # 默认处理
            return Condition(
                field=field,
                operator=Operator.MATCH,
                value=match.group(0)
            )

    def _find_rule_by_field_and_pattern(self, field: str, pattern) -> Optional[Dict]:
        """根据字段和模式查找规则"""
        pattern_str = pattern if isinstance(pattern, str) else str(pattern.pattern)
        for rule in self.rules:
            if rule.get('field') == field:
                patterns = rule.get('patterns', [])
                if pattern_str in patterns:
                    return rule
        return None

    def _process_age(self, match: re.Match, query: str) -> Optional[Condition]:
        """处理年龄匹配"""
        text = match.group(0)
        groups = match.groups()

        # 尝试将捕获组转换为数字（支持中文数字）
        def to_number(s: str) -> Optional[int]:
            if not s:
                return None
            if s.isdigit():
                return int(s)
            # 中文数字转换
            try:
                return chinese_to_arabic(s)
            except:
                return None

        if "以上" in text or "超过" in text or "大于" in text:
            age = to_number(groups[0])
            if age is not None:
                return Condition(
                    field="age",
                    operator=Operator.GTE,
                    value=age
                )
        elif "以下" in text or "小于" in text:
            age = to_number(groups[0])
            if age is not None:
                return Condition(
                    field="age",
                    operator=Operator.LTE,
                    value=age
                )
        elif "多岁" in text:
            # 处理"二十多岁"、"20多岁"
            age = to_number(groups[0])
            if age is not None:
                # 返回一个范围，例如"二十多岁"表示20-29岁
                return Condition(
                    field="age",
                    operator=Operator.RANGE,
                    value=RangeValue(min=age, max=age + 9)
                )
        elif len(groups) >= 2 and groups[1]:
            # 范围
            min_age = to_number(groups[0])
            max_age = to_number(groups[1])
            if min_age is not None and max_age is not None:
                return Condition(
                    field="age",
                    operator=Operator.RANGE,
                    value=RangeValue(min=min_age, max=max_age)
                )
        elif groups[0]:
            # 单个年龄值（如"二十岁"、"20岁"）
            age = to_number(groups[0])
            if age is not None:
                return Condition(
                    field="age",
                    operator=Operator.MATCH,
                    value=age
                )

        return None

    def _process_insurance_type(self, match: re.Match, query: str) -> Optional[Condition]:
        """处理险种匹配"""
        insurance_type = match.group(1)
        # 映射到标准名称
        standard_type = self.insurance_mapping.get(insurance_type, insurance_type)

        # 检查是否有否定词
        has_negation = any(neg in query[:match.start()] for neg in self.negation_words)

        operator = Operator.NOT_CONTAINS if has_negation else Operator.CONTAINS

        return Condition(
            field="held_product_category",
            operator=operator,
            value=standard_type
        )

    def _process_marital_status(self, match: re.Match) -> Optional[Condition]:
        """处理婚姻状况"""
        status = match.group(1) if match.groups() else match.group(0)

        # 映射同义词到标准值
        status_mapping = {
            '刚结婚': '已婚',
            '新婚': '已婚',
            '结婚': '已婚'
        }

        standard_status = status_mapping.get(status, status)

        return Condition(
            field="marital_status",
            operator=Operator.MATCH,
            value=standard_status
        )

    def _process_children(self, match: re.Match) -> Optional[Condition]:
        """处理子女信息"""
        groups = match.groups()

        # 检查是否有年龄范围 (子女.*?(\d+)[-~到](\d+).*?(岁|周岁))
        if len(groups) >= 2 and groups[0] and groups[1]:
            min_age = int(groups[0])
            max_age = int(groups[1])
            return Condition(
                field="children",
                operator=Operator.RANGE,
                value=RangeValue(min=min_age, max=max_age)
            )

        # 检查是否有/无子女
        has_children = "有" in match.group(0)
        return Condition(
            field="children",
            operator=Operator.MATCH,
            value="有" if has_children else "无"
        )

    def _process_premium(self, match: re.Match) -> Optional[Condition]:
        """处理保费"""
        groups = match.groups()

        # 转换函数（支持中文数字）
        def to_number(s: str) -> Optional[int]:
            if not s:
                return None
            if s.isdigit():
                return int(s)
            try:
                return chinese_to_arabic(s)
            except:
                return None

        if "以上" in match.group(0):
            amount = to_number(groups[0])
            if amount is not None:
                if "万" in match.group(0):
                    amount *= 10000
                return Condition(
                    field="annual_premium",
                    operator=Operator.GTE,
                    value=amount
                )
        elif len(groups) >= 2 and groups[1]:
            min_amount = to_number(groups[0])
            max_amount = to_number(groups[1])
            if min_amount is not None and max_amount is not None:
                if "万" in match.group(0):
                    min_amount *= 10000
                    max_amount *= 10000
                return Condition(
                    field="annual_premium",
                    operator=Operator.RANGE,
                    value=RangeValue(min=min_amount, max=max_amount)
                )
        return None

    def _process_income(self, match: re.Match) -> Optional[Condition]:
        """处理收入"""
        groups = match.groups()
        field = "annual_income" if "年收入" in match.group(0) else "household_income"

        # 转换函数（支持中文数字）
        def to_number(s: str) -> Optional[int]:
            if not s:
                return None
            if s.isdigit():
                return int(s)
            try:
                return chinese_to_arabic(s)
            except:
                return None

        if "以上" in match.group(0):
            amount = to_number(groups[1])
            if amount is not None:
                if "万" in match.group(0):
                    amount *= 10000
                return Condition(
                    field=field,
                    operator=Operator.GTE,
                    value=amount
                )
        elif len(groups) >= 2 and groups[1]:
            min_amount = to_number(groups[1])
            max_amount = to_number(groups[2]) if len(groups) > 2 and groups[2] else min_amount
            if min_amount is not None and max_amount is not None:
                if "万" in match.group(0):
                    min_amount *= 10000
                    max_amount *= 10000
                return Condition(
                    field=field,
                    operator=Operator.RANGE,
                    value=RangeValue(min=min_amount, max=max_amount)
                )
        return None

    def _process_product(self, match: re.Match, query: str) -> Optional[Condition]:
        """处理产品名称"""
        product_name = match.group(1)

        # 检查是否有否定词
        has_negation = any(neg in query[:match.start()] for neg in self.negation_words)
        operator = Operator.NOT_CONTAINS if has_negation else Operator.CONTAINS

        return Condition(
            field="life_insurance_product",
            operator=operator,
            value=product_name
        )


if __name__ == '__main__':
    level2 = Level2TemplateMatcher()
    query = '45岁以上未配置养老险的客户'
    response = level2.match(query)
    print(response)