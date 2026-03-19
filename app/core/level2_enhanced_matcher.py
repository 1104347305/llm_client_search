"""
Level 2: 增强规则引擎 - 基于 YAML 配置的灵活规则匹配
支持直接在配置文件中定义 field、operator、value
"""
import re
import yaml
from itertools import product as itertools_product
from typing import List, Tuple, Dict, Any, Optional, Set
from pathlib import Path
from loguru import logger
from app.models.schemas import Condition, Operator, RangeValue
from app.models.field_mapping import NEGATION_WORDS


class RuleMatch:
    """规则匹配结果"""
    def __init__(self, rule_name: str, condition: Condition,
                 start: int, end: int, priority: int):
        self.rule_name = rule_name
        self.condition = condition
        self.start = start
        self.end = end
        self.priority = priority
        self.matched_text = ""


class Level2EnhancedMatcher:
    """增强规则匹配器 - 支持 YAML 配置的完整条件定义"""

    def __init__(self, config_path: str = "config/enhanced_rules.yaml"):
        """初始化增强匹配器"""
        logger.debug(f"Initializing Level2EnhancedMatcher with config: {config_path}")

        if not Path(config_path).is_absolute():
            path1 = Path(config_path)
            path2 = Path(__file__).parent.parent.parent / config_path

            if path1.exists():
                self.config_path = path1
            elif path2.exists():
                self.config_path = path2
            else:
                self.config_path = path1
                logger.warning(f"Config file not found: {config_path}")
        else:
            self.config_path = Path(config_path)

        self.rules = []
        self.composite_rules = []
        self.negation_words = NEGATION_WORDS
        self.position_words: List[str] = []
        self.value_mappings = {}
        self.enum_orders = {}
        self.enum_values: Dict[str, List[str]] = {}   # 各字段的标准枚举值列表
        self._preprocess_map: List[tuple] = []         # 预归一化替换表 [(alias, std), ...]
        self._paired_requirements: Dict[str, str] = {} # field → 必须同时存在的 paired field
        self.load_config()

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

                self.rules = config.get('rules', [])
                self.composite_rules = config.get('composite_rules', [])  # 提前加载，使 _expand_pattern_vars 能处理 composite 模板
                self.negation_words = config.get('negation_words', NEGATION_WORDS)
                self.position_words = config.get('position_words', [])
                self.value_mappings = config.get('value_mappings', {})
                self.enum_orders = config.get('enum_orders', {})

                # 1. 加载内联枚举值
                self.enum_values = {
                    k: list(v) for k, v in config.get('enum_values', {}).items()
                }

                # 2. 加载外部枚举文件（大量枚举值）
                for field, rel_path in config.get('enum_files', {}).items():
                    abs_path = self.config_path.parent.parent / rel_path
                    if not abs_path.exists():
                        abs_path = Path(rel_path)
                    if abs_path.exists():
                        with open(abs_path, 'r', encoding='utf-8') as ef:
                            values = yaml.safe_load(ef) or []
                            self.enum_values[field] = [str(v) for v in values]
                        logger.debug(f"Loaded enum file '{field}': {len(self.enum_values[field])} values")
                    else:
                        logger.warning(f"Enum file not found: {rel_path}")

                # 3. 展开 pattern_vars 占位符（如 {CW}）
                self._pattern_vars = config.get('pattern_vars', {})
                self._expand_pattern_vars()

                # 4. 展开 patterns_template 中的 {{enum}} 占位符
                self._expand_enum_patterns()

                # 4. 构建预归一化替换表（alias → 标准值，按长度降序避免短串覆盖长串）
                self._build_preprocess_map()

                # 5. 构建 require_paired_field 映射（field → paired_field）
                self._paired_requirements = {}
                for rule in self.rules:
                    paired = rule.get('require_paired_field')
                    if paired:
                        self._paired_requirements[rule['field']] = paired

                # 6. 展开组合规则（【rule_name】引用替换；composite_rules 已在步骤1提前加载）
                self._expand_composite_refs()

                # 7. 预编译所有正则表达式以提升性能
                self._compile_patterns()

            logger.info(f"Loaded {len(self.rules)} enhanced rules, "
                        f"{len(self.composite_rules)} composite rules, "
                        f"{len(self.enum_values)} enum fields from {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to load enhanced rules: {e}")
            self.rules = []

    def _expand_pattern_vars(self):
        """将 patterns 中的 {VAR} 占位符替换为 pattern_vars 中定义的字符集。
        使用 str.replace 而非 str.format，避免正则量词 {1,4} 被误解析。
        同时处理 composite_rules 的 patterns，并自动在每条 composite 模板头部
        前置 {SEARCH} 前缀（若 pattern_vars 中定义了 SEARCH）。"""
        def _substitute(p: str) -> str:
            for var, val in self._pattern_vars.items():
                p = p.replace('{' + var + '}', val)
            return p

        for rule in self.rules:
            for key in ('patterns', 'patterns_template'):
                if key in rule:
                    rule[key] = [_substitute(p) for p in rule[key]]

        for rule in self.composite_rules:
            if 'patterns' in rule:
                rule['patterns'] = [_substitute(p) for p in rule['patterns']]

    def _expand_enum_patterns(self):
        """
        将规则中的 patterns_template 展开为 patterns。
        {enum}     → enum_values[enum_ref] 的捕获交替组，如 (v1|v2|v3)。
        {negation} → negation_words 的非捕获交替组，如 (?:未配置|没有|...)。
        {position} → position_words 的非捕获交替组，如 (?:购买了|持有|买了|...)。
        """
        # 预构建否定词非捕获组（按长度降序，避免短词先匹配）
        sorted_neg = sorted(self.negation_words, key=len, reverse=True)
        negation_group = '(?:' + '|'.join(re.escape(w) for w in sorted_neg) + ')'

        # 预构建持有词非捕获组（按长度降序）
        if self.position_words:
            sorted_pos = sorted(self.position_words, key=len, reverse=True)
            position_group = '(?:' + '|'.join(re.escape(w) for w in sorted_pos) + ')'
        else:
            position_group = '(?:持有|购买了?|买了?|买过|购买过|有过?|投保了|配置了?|已有)'

        for rule in self.rules:
            enum_ref = rule.get('enum_ref')
            if not enum_ref:
                continue

            values = self.enum_values.get(enum_ref, [])
            if not values:
                logger.warning(f"Rule '{rule.get('name')}' has enum_ref='{enum_ref}' but no enum_values defined")
                continue

            # 构建枚举交替组：按长度降序，避免短值先匹配
            sorted_vals = sorted(values, key=len, reverse=True)
            enum_group = '(' + '|'.join(re.escape(v) for v in sorted_vals) + ')'

            templates = rule.get('patterns_template', [])
            if not templates:
                # 默认模板：直接匹配枚举值
                templates = ['{enum}']

            rule['patterns'] = [
                t.replace('{enum}', enum_group)
                 .replace('{negation}', negation_group)
                 .replace('{position}', position_group)
                for t in templates
            ]
            logger.debug(f"Expanded rule '{rule.get('name')}' with {len(values)} enum values")

    def _build_preprocess_map(self):
        """
        构建查询预归一化替换表：将 value_mappings 中所有别名合并为单一正则，
        使用 re.sub 单次扫描替换，避免级联替换（如 本科→大学本科 后大学再次被替换）。
        """
        lookup: dict[str, str] = {}
        for field_mappings in self.value_mappings.values():
            for alias, std in field_mappings.items():
                # 包含自映射（alias == std）：自映射在正则交替中占位，防止短别名匹配其前缀
                # 例：黄金V1→黄金V1 使 "黄金V1" 优先于 "黄金"→"黄金V1" 被替换，避免残留 "V1"
                lookup[alias] = std
        # 按长度降序构建交替正则，长串优先避免短串先匹配（如"医疗险"优先于"医疗"）
        sorted_aliases = sorted(lookup.keys(), key=len, reverse=True)
        if sorted_aliases:
            self._preprocess_pattern = re.compile(
                '|'.join(re.escape(a) for a in sorted_aliases)
            )
        else:
            self._preprocess_pattern = None
        self._preprocess_lookup = lookup
        logger.debug(f"Built preprocess map with {len(lookup)} alias entries")

    def _preprocess_query(self, query: str) -> str:
        """
        将查询文本中的别名替换为标准枚举值（在正则匹配前执行）。
        使用单次 re.sub 扫描，不会对替换结果再次匹配，避免级联替换。
        例："刚结婚" → "已婚"，"本科学历以上" → "大学本科学历以上"
        """
        if not self._preprocess_pattern:
            return query
        normalized = self._preprocess_pattern.sub(
            lambda m: self._preprocess_lookup[m.group(0)], query
        )
        if normalized != query:
            logger.debug(f"Preprocess: '{query}' → '{normalized}'")
        return normalized

    def _expand_composite_refs(self):
        """
        展开 composite_rules 中 pattern 模板里的 【rule_name】 占位符。

        每个 【rule_name】 的所有 patterns 均参与笛卡尔积展开，生成所有组合变体：
          _expanded_variants : [(pattern_str, sub_rules_offsets), ...]
                               pattern_str      = 展开后的完整正则字符串
                               sub_rules_offsets = [(sub_rule, group_offset), ...]

        composite_rules 还支持 extra_conditions 列表，用于附加纯静态条件
        （不依赖捕获组，例如 field=investable_assets, value=高净值）。
        """
        name_to_rule: Dict[str, Dict] = {r['name']: r for r in self.rules}

        for comp_rule in self.composite_rules:
            templates = comp_rule.get('patterns', [])
            if not templates and comp_rule.get('pattern'):
                templates = [comp_rule['pattern']]

            all_variants: List[tuple] = []  # (pattern_str, sub_rules_offsets)

            for tmpl in templates:
                refs = re.findall(r'【([^】]+)】', tmpl)
                ref_rules: List[Dict] = []
                ref_all_patterns: List[List[str]] = []
                valid = True

                for ref_name in refs:
                    sub_rule = name_to_rule.get(ref_name)
                    if not sub_rule:
                        logger.warning(
                            f"Composite '{comp_rule['name']}': rule '{ref_name}' not found"
                        )
                        valid = False
                        break
                    sub_pats = sub_rule.get('patterns', [])
                    if not sub_pats:
                        logger.warning(
                            f"Composite '{comp_rule['name']}': rule '{ref_name}' has no patterns"
                        )
                        valid = False
                        break
                    ref_rules.append(sub_rule)
                    ref_all_patterns.append(sub_pats)

                if not valid:
                    continue

                # 笛卡尔积：每个引用规则的所有 patterns 均参与组合
                for combo in itertools_product(*ref_all_patterns):
                    expanded = tmpl
                    current_offset = 0
                    sub_rules_offsets: List[tuple] = []

                    for ref_name, sub_rule, sub_pat in zip(refs, ref_rules, combo):
                        try:
                            n_groups = re.compile(sub_pat).groups
                        except re.error:
                            n_groups = 0
                        sub_rules_offsets.append((sub_rule, current_offset))
                        current_offset += n_groups
                        expanded = expanded.replace(f'【{ref_name}】', sub_pat, 1)

                    # 对展开后的 pattern 再次应用 pattern_vars 替换（处理模板中残留的 {position} 等占位符）
                    for var, val in self._pattern_vars.items():
                        expanded = expanded.replace('{' + var + '}', val)

                    all_variants.append((expanded, sub_rules_offsets))
                    logger.debug(
                        f"Composite '{comp_rule['name']}' variant: {expanded[:80]}..."
                    )

            comp_rule['_expanded_variants'] = all_variants
            logger.info(
                f"Composite '{comp_rule['name']}': {len(all_variants)} expanded variants"
            )

    def _compile_patterns(self):
        """
        预编译所有正则表达式以提升匹配性能。
        将字符串模式编译为re.Pattern对象，避免每次查询时重复编译。
        """
        # 编译普通规则的patterns
        for rule in self.rules:
            patterns = rule.get('patterns', [])
            compiled = []
            for pattern_str in patterns:
                try:
                    compiled.append(re.compile(pattern_str))
                except re.error as e:
                    logger.warning(f"Failed to compile pattern in rule '{rule.get('name')}': {e}")
            rule['_compiled_patterns'] = compiled

        # 编译组合规则的expanded_variants
        for comp_rule in self.composite_rules:
            variants = comp_rule.get('_expanded_variants', [])
            compiled_variants = []
            for pattern_str, sub_rules_offsets in variants:
                try:
                    compiled_variants.append((re.compile(pattern_str), sub_rules_offsets))
                except re.error as e:
                    logger.warning(f"Failed to compile composite pattern in rule '{comp_rule.get('name')}': {e}")
            comp_rule['_compiled_variants'] = compiled_variants

        logger.info(f"Compiled {sum(len(r.get('_compiled_patterns', [])) for r in self.rules)} "
                    f"regular patterns and {sum(len(r.get('_compiled_variants', [])) for r in self.composite_rules)} "
                    f"composite patterns")

    def _build_conditions_from_sub_rules(
        self, comp_rule: Dict, match: re.Match, query: str,
        sub_rules_offsets: List[tuple] = None
    ) -> List[Condition]:
        """
        从一次 composite fullmatch 中提取多个 Condition。

        利用 sub_rules_offsets 中的 group_offset 调整各子规则的捕获组编号，
        复用 _build_condition 完成实际条件构建。

        extra_conditions 中的静态条件（不依赖捕获组）直接追加。
        """
        conditions: List[Condition] = []

        if sub_rules_offsets is None:
            sub_rules_offsets = []

        for sub_rule, offset in sub_rules_offsets:
            # 调整 value_config 中的 group 编号
            orig_value = sub_rule.get('value')
            if isinstance(orig_value, dict):
                adj_value = dict(orig_value)
                for key in ('group', 'min_group', 'max_group', 'days_group'):
                    if key in adj_value and isinstance(adj_value[key], int):
                        adj_value[key] += offset
            else:
                adj_value = orig_value

            # 临时 patch：_group_offset 供 _build_condition 的否定检测使用
            patched = {**sub_rule, 'value': adj_value, '_group_offset': offset}
            cond = self._build_condition(patched, match, query)
            if cond:
                conditions.append(cond)

        # 附加纯静态条件（如 investable_assets=高净值）
        for spec in comp_rule.get('extra_conditions', []):
            field = spec.get('field')
            operator_str = spec.get('operator', 'MATCH')
            value = spec.get('value')
            if field and value is not None:
                conditions.append(
                    Condition(field=field,
                              operator=self._get_operator(operator_str, False),
                              value=value)
                )

        return conditions

    async def match(self, query: str) -> Tuple[List[Condition], str, bool]:
        """
        执行规则匹配（异步版本）

        Args:
            query: 用户查询

        Returns:
            (conditions, remaining_text, has_residual)
        """
        # 预归一化：将查询文本中的别名替换为标准值，之后 pattern 只需匹配标准值
        normalized_query = self._preprocess_query(query)

        # ===== 优先尝试组合规则（fullmatch，一次提取多个条件）=====
        for rule in self.composite_rules:
            rule_name = rule.get('name', 'unknown')
            # 使用预编译的正则表达式
            for compiled_pattern, sub_rules_offsets in rule.get('_compiled_variants', []):
                if not compiled_pattern:
                    continue
                try:
                    m = compiled_pattern.fullmatch(normalized_query)
                    if m:
                        comp_conds = self._build_conditions_from_sub_rules(
                            rule, m, normalized_query, sub_rules_offsets
                        )
                        if comp_conds:
                            logger.info(
                                f"Composite rule '{rule_name}' fullmatch "
                                f"→ {len(comp_conds)} conditions"
                            )
                            return comp_conds, '', False
                except re.error as e:
                    logger.warning(f"Composite pattern error '{rule_name}': {e}")

        all_matches = []

        # 第一步: 收集所有匹配（使用归一化后的查询）
        for rule in self.rules:
            rule_name = rule.get('name', 'unknown')
            compiled_patterns = rule.get('_compiled_patterns', [])
            priority = rule.get('priority', 0)

            for compiled_pattern in compiled_patterns:
                try:
                    match = compiled_pattern.fullmatch(normalized_query)
                    if match:
                        condition = self._build_condition(rule, match, normalized_query)
                        if condition:
                            if match.lastindex and match.lastindex >= 1:
                                start = match.start(1)
                                end = match.end(match.lastindex)
                            else:
                                start = match.start()
                                end = match.end()

                            rule_match = RuleMatch(
                                rule_name=rule_name,
                                condition=condition,
                                start=start,
                                end=end,
                                priority=priority
                            )
                            rule_match.matched_text = match.group(0)
                            all_matches.append(rule_match)
                            logger.debug(f"Rule '{rule_name}' fullmatch: {match.group(0)}")
                except re.error as e:
                    logger.warning(f"Invalid regex pattern: {pattern_str}, error: {e}")

        # 第二步: 解决冲突
        final_matches = self._resolve_conflicts(all_matches)

        # 第三步: 提取条件
        conditions = [m.condition for m in final_matches]

        # 第三步（补充）: 验证 require_paired_field 约束
        # 若某字段要求成对出现的字段不存在，则丢弃该条件（让查询降级到 LLM）
        if self._paired_requirements:
            condition_fields = {c.field for c in conditions}
            valid_matches = []
            for m in final_matches:
                paired = self._paired_requirements.get(m.condition.field)
                if paired and paired not in condition_fields:
                    logger.info(
                        f"Dropping condition '{m.condition.field}={m.condition.value}' — "
                        f"required paired field '{paired}' not found in conditions"
                    )
                else:
                    valid_matches.append(m)
            if len(valid_matches) != len(final_matches):
                final_matches = valid_matches
                conditions = [m.condition for m in final_matches]

        # 第四步: 计算剩余文本（基于归一化后的查询，确保位置一致）
        extracted_positions = set()
        for m in final_matches:
            extracted_positions.update(range(m.start, m.end))

        remaining_chars = [char for i, char in enumerate(normalized_query) if i not in extracted_positions]
        remaining_text = ''.join(remaining_chars)
        remaining_text = re.sub(r'\s+', ' ', remaining_text).strip()

        has_residual = len(remaining_text) > 0

        logger.info(f"Level 2 Enhanced matched {len(conditions)} conditions")
        return conditions, remaining_text, has_residual

    def _build_condition(self, rule: Dict, match: re.Match, query: str) -> Optional[Condition]:
        """根据规则配置构建条件"""
        field = rule.get('field')
        operator_str = rule.get('operator')
        value_type = rule.get('value_type')
        value_config = rule.get('value')
        negation_support = rule.get('negation_support', False)

        if not field or not operator_str:
            return None

        # 检查否定词
        has_negation = False
        if negation_support:
            # _group_offset: 组合规则嵌入时，该子规则捕获组在完整 match 中的偏移量
            _goff = rule.get('_group_offset', 0)
            _first_cap = 1 + _goff
            cap_start = (match.start(_first_cap)
                         if match.lastindex and match.lastindex >= _first_cap
                         else match.start())
            check_start = max(0, cap_start - 20)
            context_before = query[check_start:cap_start]
            # 进一步优化：检查否定词和匹配内容之间是否有标点符号分隔
            # 如果有顿号、逗号等分隔，则否定词不生效
            for neg in self.negation_words:
                if neg in context_before:
                    # 检查否定词到匹配位置之间的文本
                    neg_pos = context_before.rfind(neg)
                    between_text = context_before[neg_pos + len(neg):]
                    # 如果中间有标点符号（顿号、逗号、分号），则否定词不生效
                    if not any(punct in between_text for punct in ['、', '，', ',', '；', ';']):
                        has_negation = True
                        break

        # 确定操作符
        operator = self._get_operator(operator_str, has_negation)

        # EXISTS/NOT_EXISTS 无需 value，直接构建条件
        if operator_str in ("EXISTS", "NOT_EXISTS"):
            return Condition(field=field, operator=self._get_operator(operator_str, False))

        # 提取值
        value = self._extract_value(value_type, value_config, match)
        if value is None:
            return None

        # 应用 value_mappings 标准化（仅对字符串值且非 enum_ref 规则生效）
        # enum_ref 规则在查询预归一化阶段已完成别名→标准值的转换，此处跳过避免重复
        if isinstance(value, str) and field in self.value_mappings and not rule.get('enum_ref'):
            value = self.value_mappings[field].get(value, value)

        # enum_gte / enum_lte value_type：按 enum_orders 展开为有序列表（operator 已是 CONTAINS）
        if value_type in ("enum_gte", "enum_lte") and isinstance(value, str):
            op_str = "ENUM_GTE" if value_type == "enum_gte" else "ENUM_LTE"
            resolved = self._resolve_enum_order(field, op_str, value)
            if resolved is not None:
                value = resolved
            else:
                # 降级：找不到枚举顺序时回退为精确匹配
                operator = Operator.MATCH
                logger.warning(f"{value_type} fallback to MATCH for field='{field}' value='{value}'")

        return Condition(field=field, operator=operator, value=value)

    def _get_operator(self, operator_str: str, has_negation: bool) -> Operator:
        """获取操作符"""
        # 如果有否定词，转换操作符
        if has_negation:
            if operator_str == "CONTAINS":
                return Operator.NOT_CONTAINS
            # 其他操作符暂不支持否定

        # 映射字符串到 Operator 枚举
        operator_map = {
            "MATCH": Operator.MATCH,
            "GTE": Operator.GTE,
            "LTE": Operator.LTE,
            "RANGE": Operator.RANGE,
            "CONTAINS": Operator.CONTAINS,
            "NOT_CONTAINS": Operator.NOT_CONTAINS,
            "EXISTS": Operator.EXISTS,
            "NOT_EXISTS": Operator.NOT_EXISTS,
            "NESTED_MATCH": Operator.NESTED_MATCH,
        }
        return operator_map.get(operator_str, Operator.MATCH)

    def _extract_value(self, value_type: str, value_config: Any, match: re.Match) -> Any:
        """根据值类型提取值"""
        if value_type == "static":
            # 静态值
            return value_config

        elif value_type == "capture":
            # 从正则捕获组提取
            if isinstance(value_config, dict):
                group = value_config.get('group', 1)
                transform = value_config.get('transform')

                try:
                    captured = match.group(group)
                    if not captured:
                        return None

                    # 应用转换
                    return self._apply_transform(captured, transform, value_config)
                except IndexError:
                    return None
            else:
                # 简单捕获
                try:
                    return match.group(1)
                except IndexError:
                    return None

        elif value_type in ("enum_gte", "enum_lte"):
            # 与 capture 相同：先捕获字符串，_build_condition 再展开为有序列表
            group = value_config.get('group', 1) if isinstance(value_config, dict) else 1
            try:
                captured = match.group(group)
                return captured if captured else None
            except IndexError:
                return None

        elif value_type == "range":
            # 范围值（从配置或捕获组）
            if isinstance(value_config, dict):
                if 'min_group' in value_config and 'max_group' in value_config:
                    # 从捕获组提取范围
                    try:
                        min_val = match.group(value_config['min_group'])
                        max_val = match.group(value_config['max_group'])
                        transform = value_config.get('transform')

                        min_val = self._apply_transform(min_val, transform, value_config)
                        max_val = self._apply_transform(max_val, transform, value_config)

                        return RangeValue(min=min_val, max=max_val)
                    except IndexError:
                        return None
                elif 'min' in value_config and 'max' in value_config:
                    # 静态范围
                    return RangeValue(min=value_config['min'], max=value_config['max'])
            return None

        elif value_type == "date_range_dynamic":
            # 动态日期范围（运行时计算）：next_month / current_month / next_n_days
            return self._compute_dynamic_date_range(value_config or {}, match)

        return None

    def _compute_dynamic_date_range(self, config: Dict, match: Optional[re.Match] = None) -> Optional[RangeValue]:
        """动态计算日期范围（next_month / current_month / next_n_days / next_week / last_n_days / last_year）"""
        import calendar
        from datetime import date, timedelta

        date_range = config.get("date_range", "")
        fmt_str = config.get("format", "YYYY-MM-DD")

        # 判断格式：MM-DD 或 YYYY-MM-DD
        if fmt_str == "MM-DD":
            date_fmt = "%m-%d"
            month_day_only = True
        else:
            date_fmt = "%Y-%m-%d" if "YYYY-MM-DD" in fmt_str else "%Y%m%d"
            month_day_only = False

        today = date.today()

        if date_range == "today":
            # 今天
            if month_day_only:
                return RangeValue(
                    min=today.strftime("%m-%d"),
                    max=today.strftime("%m-%d"),
                )
            return RangeValue(
                min=today.strftime(date_fmt),
                max=today.strftime(date_fmt),
            )

        elif date_range == "tomorrow":
            # 明天
            tomorrow = today + timedelta(days=1)
            if month_day_only:
                return RangeValue(
                    min=tomorrow.strftime("%m-%d"),
                    max=tomorrow.strftime("%m-%d"),
                )
            return RangeValue(
                min=tomorrow.strftime(date_fmt),
                max=tomorrow.strftime(date_fmt),
            )

        elif date_range == "day_after_tomorrow":
            # 后天
            day_after = today + timedelta(days=2)
            if month_day_only:
                return RangeValue(
                    min=day_after.strftime("%m-%d"),
                    max=day_after.strftime("%m-%d"),
                )
            return RangeValue(
                min=day_after.strftime(date_fmt),
                max=day_after.strftime(date_fmt),
            )

        elif date_range == "next_month":
            year = today.year + 1 if today.month == 12 else today.year
            month = 1 if today.month == 12 else today.month + 1
            last_day = calendar.monthrange(year, month)[1]
            if month_day_only:
                return RangeValue(
                    min=f"{month:02d}-01",
                    max=f"{month:02d}-{last_day:02d}",
                )
            return RangeValue(
                min=date(year, month, 1).strftime(date_fmt),
                max=date(year, month, last_day).strftime(date_fmt),
            )

        elif date_range == "current_month":
            year, month = today.year, today.month
            last_day = calendar.monthrange(year, month)[1]
            if month_day_only:
                return RangeValue(
                    min=f"{month:02d}-01",
                    max=f"{month:02d}-{last_day:02d}",
                )
            return RangeValue(
                min=date(year, month, 1).strftime(date_fmt),
                max=date(year, month, last_day).strftime(date_fmt),
            )

        elif date_range == "next_n_days":
            # 优先从捕获组读取天数
            n = config.get("days", 30)
            days_group = config.get("days_group")
            if days_group and match:
                try:
                    n = int(match.group(days_group))
                except (IndexError, ValueError):
                    pass
            # 从明天开始往后延n天
            start_date = today + timedelta(days=1)
            end_date = start_date + timedelta(days=n - 1)
            if month_day_only:
                return RangeValue(
                    min=start_date.strftime("%m-%d"),
                    max=end_date.strftime("%m-%d"),
                )
            return RangeValue(
                min=start_date.strftime(date_fmt),
                max=end_date.strftime(date_fmt),
            )

        elif date_range == "next_week":
            # 下周：从下周一到下周日
            days_until_next_monday = (7 - today.weekday()) % 7
            if days_until_next_monday == 0:
                days_until_next_monday = 7
            next_monday = today + timedelta(days=days_until_next_monday)
            next_sunday = next_monday + timedelta(days=6)
            if month_day_only:
                return RangeValue(
                    min=next_monday.strftime("%m-%d"),
                    max=next_sunday.strftime("%m-%d"),
                )
            return RangeValue(
                min=next_monday.strftime(date_fmt),
                max=next_sunday.strftime(date_fmt),
            )

        elif date_range == "last_n_days":
            n = config.get("days", 30)
            days_group = config.get("days_group")
            if days_group and match:
                try:
                    n = int(match.group(days_group))
                except (IndexError, ValueError):
                    pass
            start_date = today - timedelta(days=n)
            if month_day_only:
                return RangeValue(
                    min=start_date.strftime("%m-%d"),
                    max=today.strftime("%m-%d"),
                )
            return RangeValue(
                min=start_date.strftime(date_fmt),
                max=today.strftime(date_fmt),
            )

        elif date_range == "last_month":
            # 上个月
            if today.month == 1:
                year, month = today.year - 1, 12
            else:
                year, month = today.year, today.month - 1
            last_day = calendar.monthrange(year, month)[1]
            if month_day_only:
                return RangeValue(
                    min=f"{month:02d}-01",
                    max=f"{month:02d}-{last_day:02d}",
                )
            return RangeValue(
                min=date(year, month, 1).strftime(date_fmt),
                max=date(year, month, last_day).strftime(date_fmt),
            )

        elif date_range == "last_year":
            if month_day_only:
                # MM-DD 格式不适用于 last_year，返回 None
                logger.warning("last_year not supported for MM-DD format")
                return None
            last_year = today.year - 1
            return RangeValue(
                min=date(last_year, 1, 1).strftime(date_fmt),
                max=date(last_year, 12, 31).strftime(date_fmt),
            )

        logger.warning(f"Unknown date_range type: '{date_range}'")
        return None

    def _apply_transform(self, value: str, transform: Optional[str], config: Dict) -> Any:
        """应用值转换"""
        if not transform:
            return value

        if transform == "int":
            return int(value)

        elif transform == "multiply":
            multiplier = config.get('multiplier', 1)
            # 支持中文数字转换
            if value in ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']:
                cn_num_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
                              '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
                value = str(cn_num_map.get(value, value))
            return int(value) * multiplier

        elif transform == "plus_range":
            # 用于"20多岁" -> 21-29
            base = int(value)
            offset = config.get('offset', 1)
            range_size = config.get('range', 9)
            return RangeValue(min=base + offset, max=base + range_size)

        elif transform == "ensure_suffix":
            # 确保有后缀
            suffix = config.get('suffix', '')
            if not value.endswith(suffix):
                return value + suffix
            return value

        elif transform == "exact_range":
            # 将单个数值转为精确范围 {min: n, max: n}，用于精确年龄等数值匹配
            n = int(value)
            return RangeValue(min=n, max=n)

        elif transform == "year_to_birth_range":
            # 将出生年份转为 client_birth 日期范围，如 "1953" → {min:"19530101", max:"19531231"}
            year = int(value)
            return RangeValue(min=f"{year}0101", max=f"{year}1231")

        elif transform == "chinese_decade_plus_range":
            # 将中文年代词转为整数后应用 plus_range
            # 例如: "二十" -> 20, "三十" -> 30, "十" -> 10
            chinese_decade_map = {
                '十': 10, '二十': 20, '三十': 30, '四十': 40,
                '五十': 50, '六十': 60, '七十': 70, '八十': 80, '九十': 90,
            }
            base = chinese_decade_map.get(value.strip())
            if base is None:
                return None
            offset = config.get('offset', 1)
            range_size = config.get('range', 9)
            return RangeValue(min=base + offset, max=base + range_size)

        return value

    def _resolve_enum_order(self, field: str, operator_str: str, value: str) -> Optional[List[str]]:
        """
        根据 enum_orders 将枚举值展开为有序列表。

        Args:
            field: 字段名
            operator_str: "ENUM_GTE" 或 "ENUM_LTE"
            value: 已经过 value_mappings 标准化的枚举值

        Returns:
            展开后的枚举列表（含边界值），找不到时返回 None
        """
        order = self.enum_orders.get(field, [])
        if not order:
            logger.warning(f"No enum_orders defined for field '{field}'")
            return None

        # 若直接找不到，再尝试通过 value_mappings 标准化一次
        if value not in order:
            std = self.value_mappings.get(field, {}).get(value, value)
            if std not in order:
                logger.warning(f"Value '{value}' not in enum_orders['{field}']: {order}")
                return None
            value = std

        idx = order.index(value)
        if operator_str == "ENUM_GTE":
            result = order[idx:]
        else:  # ENUM_LTE
            result = order[:idx + 1]

        logger.debug(f"ENUM resolve field='{field}' {operator_str} '{value}' → {result}")
        return result

    def _resolve_conflicts(self, matches: List[RuleMatch]) -> List[RuleMatch]:
        """
        解决匹配冲突
        策略：
        1. 同字段只保留优先级最高的一个
        2. 位置有重叠时，保留优先级更高的一个
        3. 不同字段且位置不重叠，允许共存

        Args:
            matches: 所有匹配结果

        Returns:
            解决冲突后的匹配列表
        """
        if not matches:
            return []

        # 按优先级降序,然后按起始位置升序排序
        sorted_matches = sorted(matches, key=lambda m: (-m.priority, m.start))

        final_matches = []
        used_fields = set()  # 记录已使用的字段
        used_positions = []  # 记录已使用的位置范围 [(start, end), ...]

        for match in sorted_matches:
            field = match.condition.field

            # 检查是否同字段已有更高优先级的条件
            if field in used_fields:
                logger.debug(f"Skipped duplicate field '{field}': {match.rule_name}")
                continue

            # 检查位置是否与已选中的匹配有重叠
            has_overlap = False
            for used_start, used_end in used_positions:
                # 检查是否有重叠：[start, end) 与 [used_start, used_end) 有交集
                if not (match.end <= used_start or match.start >= used_end):
                    has_overlap = True
                    logger.debug(f"Skipped overlapping match '{match.rule_name}' at [{match.start}:{match.end}]")
                    break

            if has_overlap:
                continue

            final_matches.append(match)
            used_fields.add(field)
            used_positions.append((match.start, match.end))
            logger.debug(f"Selected: {match.rule_name} at [{match.start}:{match.end}]")

        # 按原始位置排序
        final_matches.sort(key=lambda m: m.start)
        return final_matches

    def get_rules_count(self) -> int:
        """获取规则数量"""
        return len(self.rules)

    def debug_info(self) -> dict:
        """获取调试信息"""
        return {
            "config_path": str(self.config_path.absolute()),
            "config_exists": self.config_path.exists(),
            "rules_count": len(self.rules),
            "rules_loaded": self.rules is not None and len(self.rules) > 0,
            "enum_fields": list(self.enum_values.keys()),
            "preprocess_aliases": len(self._preprocess_lookup),
        }

if __name__ == '__main__':
    from query_router import QueryRouter
    from app.models.schemas import (
        SearchRequest,
        RequestHeader
    )
    import asyncio
    import requests


    async def process_question():
        parsed = await router.route_with_peeling(question)
        return parsed

    router = QueryRouter()
    questions = [
        '姓张的客户',
        '名字带伟的客户',
        '张珊',
        '15817760299',
        '手机号158开头的客户',
        "手机号段581776的客户",
        "手机尾号0299的客户",
        '身份证号510101196109291482',
        '510101开头的身份证客户',
        '身份证尾号9291482的客户',
        '保单号为：P644037341678127',
        '保单号P644037的客户',
        '保单号78127结尾的客户',
        '本月生日的客户',
        '下个月生日的客户',
        '未来一周生日的客户',
        '1953年出生的客户',
        '20至30岁的客户',
        '查找本科学历以上的客户',
        '学历为本科的客户',
        '客户号为C335906420260306的客户',
        'C335906的客户',
        '420260306',
        '中温客户',
        '客温为高温的客户',
        '低温和中温的客户',
        '中温及以上的客户',
        '邻退小康',
        '有邻退小康标签的客户',
        '有哪些中年焦虑的客户',
        '黄金V1',
        '铂金以上客户',
        '原黄金VIP客户',
        '仅仅是投保人的客户',
        '存续单客户',
        '在职有效单的客户',
        '买了金瑞人生20，但是没有配置盛世金越的客户',
        '购买了学平险产品的客户',
        '未购买学平险产品的客户',
        '有过综拓产品理赔报案的客户',
        '10天内到期的短期保单',
        '购买了意健险的客户',
        '未购买意健险的客户',
        '居家潜客',
        '居家客户',
        '居家等级V1的客户',
        '预达标康养客户',
        '逸享会员客户',
        '安有护国际版客户',
        '安有护客户',
        '预达标臻享家医客户',
        '臻享家医客户',
        '未成年子女',
        '购买过e生保，并且生效中的客户',
        '有等待续保保单的客户',
        '有应缴日在下周的客户',
        '下个月需要缴费的客户',
        '购买过两全产品的客户',
        '有除责条款的客户',
        '有降档条款的客户',
        '有减费的客户',
        '购买过守护重疾26的客户',
        '购买过两全产品的客户',
        '受益人叫张三',
        '未领取生存金的客户',
        '有生存金利息没领的客户',
        '去年理赔的客户',
        'e生保理赔过的客户',
        '平安福理赔客户',
        '18-40岁客户',
        '61岁以上客户',
        '45岁以上未配置养老险的客户',
        '刚结婚的二十多岁青年家庭',
        '家里有小朋友但没买教育金的客户',
        '已婚、有车、没买百万医疗的客户',
        '35岁有小朋友还没配置重疾险的客户',
        '20-30岁刚结婚的青年客户',
        '有房产且未配置家财险的客户'
        '子女在小学阶段的客户',   # ？？？？
        '子女3-5周岁的客户',  # ？？？？
        '有小朋友的客户',
        '子女在上初中/高中的客户',   # ？？？？
        '已婚客户',
        '二十多岁刚结婚的青年客户',
        '未婚客户',
        '有车的客户',   # ？？？？
        '有房的客户',
        '家庭年收入50万以上的客户',
        '已婚、有车、没有配置百万医疗保险的客户',   # ????
        '35岁已婚、有子女、未配置重疾险的客户',
        '有重疾险客户',
        '所有万能险客户名单',
        '有意外医疗客户',
        '平安福客户',
        '金越司庆版客户',
        '未配置医疗险客户',
        '未购买百万医疗保险的客户',
        '青年客户没有e生保的客户',
        '我离职员工的孤儿单客户',
        '身份证过期的客户',    # 条件缺失
        '最近1年内承保的客户',    # 枚举值
        '2018年7月投保的客户',
        '客户年交保费20万以上',
        '中年重疾保额低的客户',    # 确认保额低的定义
        '没有附加险的客户',
        '5岁以上、已婚、有子女、有经济基础、未配置养老险和意外险的客户',
        '5岁以上、已婚、有子女、有经济基础、未配置养老险但配置了寿险的客户',
        '有哪些客户买了医疗险，但是没有买养老险',
        '查找买了医疗险、寿险但是没有买年金险的客户',
        '大连金州区、30-40岁、年交保费10万以上、有万能险的客户',    # 缺少地区
        '生存金账户余额超过5万的客户'
    ]

    for question in questions:
        parsed = asyncio.run(process_question())

        search_request = SearchRequest(
            header=RequestHeader(
                agent_id='A000001',
                page=1,
                size=20
            ),
            query_logic=parsed.query_logic,
            conditions=parsed.conditions,
            sort=[] or parsed.sort
        )
        print(question, '------->', search_request)