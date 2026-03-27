"""
Level 2: 增强规则引擎 - 基于 YAML 配置的灵活规则匹配
支持直接在配置文件中定义 field、operator、value
"""
import re
import sys
import yaml
from itertools import product as itertools_product
from typing import List, Tuple, Dict, Any, Optional, Set
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from loguru import logger
from config.settings import settings
from models.schemas import Condition, Operator, RangeValue
from models.field_mapping import NEGATION_WORDS
from core.time_range_resolver import resolve_dynamic_date_range


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

    def __init__(self, config_path: Optional[str] = None):
        """初始化增强匹配器"""
        config_path = config_path or settings.ENHANCED_RULES_PATH
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
        self._last_matched_patterns: List[Dict[str, Any]] = []
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
                # 从外部文件加载 value_mappings（路径从 settings 获取）
                vm_path = Path(settings.VALUE_MAPPINGS_PATH)
                if vm_path.exists():
                    with open(vm_path, 'r', encoding='utf-8') as vf:
                        self.value_mappings = yaml.safe_load(vf) or {}
                    logger.debug(f"Loaded value_mappings from {vm_path}")
                else:
                    self.value_mappings = {}
                    logger.warning(f"value_mappings_file not found: {vm_path}")
                self.enum_orders = config.get('enum_orders', {})

                # 1. 加载内联枚举值
                self.enum_values = {
                    k: list(v) for k, v in config.get('enum_values', {}).items()
                }

                # 2. 加载外部枚举文件（大量枚举值，路径基于 settings.ENUMS_DIR_PATH）
                _enums_dir = Path(settings.ENUMS_DIR_PATH)
                for field, rel_path in config.get('enum_files', {}).items():
                    abs_path = Path(rel_path) if Path(rel_path).is_absolute() else _enums_dir / Path(rel_path).name
                    if not abs_path.exists():
                        logger.warning(f"Enum file not found: {rel_path}")
                        continue
                    with open(abs_path, 'r', encoding='utf-8') as ef:
                        raw = yaml.safe_load(ef) or {}
                    if field == '__all__':
                        # 统一枚举文件：{fieldName: {values: [...], ordered: bool}}
                        for k, entry in raw.items():
                            vals = entry.get('values', []) if isinstance(entry, dict) else list(entry)
                            self.enum_values[k] = [str(v) for v in vals]
                            if isinstance(entry, dict) and entry.get('ordered'):
                                self.enum_orders[k] = [str(v) for v in vals]
                        logger.debug(f"Loaded __all__ enum file: {len(raw)} fields")
                    else:
                        # 单字段文件：支持列表格式 [...] 或字典格式 {field: {values: [...]}}
                        if isinstance(raw, list):
                            self.enum_values[field] = [str(v) for v in raw]
                        elif isinstance(raw, dict):
                            entry = raw.get(field, raw)
                            vals = entry.get('values', []) if isinstance(entry, dict) else list(entry)
                            self.enum_values[field] = [str(v) for v in vals]
                            if isinstance(entry, dict) and entry.get('ordered'):
                                self.enum_orders[field] = [str(v) for v in vals]
                        logger.debug(f"Loaded enum file '{field}': {len(self.enum_values.get(field, []))} values")

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

    async def match(self, query: str) -> List[Condition]:
        """
        执行规则匹配（异步版本）

        Args:
            query: 用户查询

        Returns:
            List[Condition]: 匹配到的条件列表
        """
        # 预归一化：将查询文本中的别名替换为标准值，之后 pattern 只需匹配标准值
        normalized_query = self._preprocess_query(query)
        self._last_matched_patterns = []

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
                        self._last_matched_patterns.append({
                            "rule_name": rule_name,
                            "pattern": compiled_pattern.pattern,
                            "matched_text": m.group(0),
                            "match_type": "composite",
                        })
                        comp_conds = self._build_conditions_from_sub_rules(
                            rule, m, normalized_query, sub_rules_offsets
                        )
                        if comp_conds:
                            logger.info(
                                f"Composite rule '{rule_name}' fullmatch "
                                f"→ {len(comp_conds)} conditions"
                            )
                            return comp_conds
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
                        self._last_matched_patterns.append({
                            "rule_name": rule_name,
                            "pattern": compiled_pattern.pattern,
                            "matched_text": match.group(0),
                            "match_type": "regular",
                        })
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

                            # 处理普通规则的 extra_conditions（静态附加条件）
                            for extra in rule.get('extra_conditions', []):
                                extra_cond = Condition(
                                    field=extra['field'],
                                    operator=self._get_operator(extra['operator'], False),
                                    value=extra.get('value'),
                                )
                                extra_match = RuleMatch(
                                    rule_name=f"{rule_name}[extra]",
                                    condition=extra_cond,
                                    start=start,
                                    end=end,
                                    priority=priority,
                                )
                                extra_match.matched_text = match.group(0)
                                all_matches.append(extra_match)

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

        logger.info(f"Level 2 Enhanced matched {len(conditions)} conditions")
        return conditions

    def recall_fields(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        基于 L2 规则做字段召回。

        与 match() 不同：
        - 不要求整句 fullmatch
        - 仅用于给 L4 提供“相关字段”上下文
        - 返回命中的字段及调试信息，不直接产出最终条件
        """
        normalized_query = self._preprocess_query(query)
        recalled: Dict[str, Dict[str, Any]] = {}

        for rule in self.rules:
            field = rule.get("field")
            if not field:
                continue

            compiled_patterns = rule.get("_compiled_patterns", [])
            priority = int(rule.get("priority", 0))
            rule_name = rule.get("name", "unknown")

            for compiled_pattern in compiled_patterns:
                try:
                    match = compiled_pattern.search(normalized_query)
                except re.error as e:
                    logger.warning(f"Invalid regex pattern in recall '{rule_name}': {e}")
                    continue

                if not match:
                    continue

                current = recalled.get(field)
                candidate = {
                    "field": field,
                    "rule_name": rule_name,
                    "pattern": compiled_pattern.pattern,
                    "matched_text": match.group(0),
                    "priority": priority,
                }

                if current is None or priority > current["priority"]:
                    recalled[field] = candidate

                for extra in rule.get("extra_conditions", []):
                    extra_field = extra.get("field")
                    if not extra_field:
                        continue
                    extra_current = recalled.get(extra_field)
                    extra_candidate = {
                        "field": extra_field,
                        "rule_name": f"{rule_name}[extra]",
                        "pattern": compiled_pattern.pattern,
                        "matched_text": match.group(0),
                        "priority": priority,
                    }
                    if extra_current is None or priority > extra_current["priority"]:
                        recalled[extra_field] = extra_candidate

        results = sorted(
            recalled.values(),
            key=lambda item: (-item["priority"], item["field"])
        )[:top_k]
        logger.debug(
            f"L2 field recall matched {len(results)} fields for query '{query}': "
            f"{[item['field'] for item in results]}"
        )
        return results

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

        # enum_gte / enum_gt / enum_lte / enum_lt value_type：
        # 按 enum_orders 展开为有序列表（operator 已是 CONTAINS）
        if value_type in ("enum_gte", "enum_gt", "enum_lte", "enum_lt") and isinstance(value, str):
            if value_type == "enum_gte":
                op_str = "ENUM_GTE"
            elif value_type == "enum_gt":
                op_str = "ENUM_GT"
            elif value_type == "enum_lte":
                op_str = "ENUM_LTE"
            else:
                op_str = "ENUM_LT"
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

        elif value_type in ("enum_gte", "enum_gt", "enum_lte", "enum_lt"):
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

        elif value_type == "exact_range":
            if isinstance(value_config, dict):
                group = value_config.get('group', 1)
                transform = value_config.get('transform', 'exact_range')
                try:
                    captured = match.group(group)
                    if not captured:
                        return None
                    return self._apply_transform(captured, transform, value_config)
                except IndexError:
                    return None

        return None

    def _compute_dynamic_date_range(self, config: Dict, match: Optional[re.Match] = None) -> Optional[RangeValue]:
        """动态计算日期范围。"""
        date_range = config.get("date_range", "")
        fmt_str = config.get("format", "YYYY-MM-DD")

        # 判断格式：MM-dd / MM-DD 或 YYYY-MM-DD
        if fmt_str.upper() == "MM-DD":
            month_day_only = True
        else:
            month_day_only = False

        resolved = resolve_dynamic_date_range(config, match=match)
        if resolved is not None:
            return resolved

        if date_range == "last_year":
            from datetime import date
            if month_day_only:
                # MM-DD 格式不适用于 last_year，返回 None
                logger.warning("last_year not supported for MM-DD format")
                return None
            today = date.today()
            last_year = today.year - 1
            return RangeValue(
                min=f"{last_year}-01-01 00:00:00" if "HH:mm:ss" in fmt_str else f"{last_year}-01-01",
                max=f"{last_year}-12-31 00:00:00" if "HH:mm:ss" in fmt_str else f"{last_year}-12-31",
            )

        elif date_range == "current_year":
            from datetime import date
            if month_day_only:
                logger.warning("current_year not supported for MM-DD format")
                return None
            today = date.today()
            return RangeValue(
                min=f"{today.year}-01-01 00:00:00" if "HH:mm:ss" in fmt_str else f"{today.year}-01-01",
                max=f"{today.year}-12-31 00:00:00" if "HH:mm:ss" in fmt_str else f"{today.year}-12-31",
            )

        elif date_range == "year_month_day":
            from datetime import date
            if month_day_only:
                logger.warning("year_month_day not supported for MM-DD format")
                return None
            try:
                if match.lastindex == 1:
                    raw = match.group(1).lstrip(".")
                    if len(raw) != 10:
                        return None
                    year, month, day = map(int, raw.split("-"))
                else:
                    year = int(match.group(1))
                    month = int(match.group(2))
                    day = int(match.group(3) or 1)
            except (TypeError, ValueError, IndexError):
                return None
            rendered = f"{year:04d}-{month:02d}-{day:02d}"
            if "HH:mm:ss" in fmt_str:
                rendered = f"{rendered} 00:00:00"
            return RangeValue(
                min=rendered,
                max=rendered,
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
            # 将单个数值转为精确范围；若配置了 range，则按左右范围展开
            n = int(value)
            spread = config.get('range')
            if isinstance(spread, int) and spread > 0:
                return RangeValue(min=n - spread, max=n + spread)
            return RangeValue(min=n, max=n)

        elif transform == "yyyymmdd_to_datetime":
            # 将 8 位日期转为接口要求的日期时间格式
            if len(value) != 8 or not value.isdigit():
                return value
            return f"{value[:4]}-{value[4:6]}-{value[6:8]} 00:00:00"

        elif transform == "year_to_birth_range":
            # 将出生年份转为接口要求的出生日期范围
            year = int(value)
            return RangeValue(
                min=f"{year}-01-01 00:00:00",
                max=f"{year}-12-31 00:00:00",
            )

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
            operator_str: "ENUM_GTE" / "ENUM_GT" / "ENUM_LTE" / "ENUM_LT"
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
        elif operator_str == "ENUM_GT":
            result = order[idx + 1:]
        elif operator_str == "ENUM_LTE":
            result = order[:idx + 1]
        else:  # ENUM_LT
            result = order[:idx]

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
            "last_matched_patterns": self._last_matched_patterns,
        }
