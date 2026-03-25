import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.level2_enhanced_matcher import Level2EnhancedMatcher


def _match(query: str):
    matcher = Level2EnhancedMatcher("config/enhanced_rules.yaml")
    return asyncio.run(matcher.match(query))


def test_age_around_alone():
    conditions = _match("找40岁左右有哪些人")
    assert len(conditions) == 1
    assert conditions[0].field == "clientAge"
    assert conditions[0].value.min == 38
    assert conditions[0].value.max == 42


def test_age_around_plus_vip():
    conditions = _match("40岁左右黄金VIP有哪些人")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("clientAge", "RANGE")].min == 38
    assert values[("clientAge", "RANGE")].max == 42
    assert values[("vipType", "MATCH")] == "原黄金VIP"


def test_shouxian_exists():
    conditions = _match("帮我查寿险有哪些人")
    assert len(conditions) == 1
    assert conditions[0].field == "productCode"
    assert conditions[0].operator.value == "EXISTS"


def test_no_insurance_maps_to_ptype_not_exists():
    conditions = _match("找45岁以上没有配置保险的")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert ("clientAge", "GTE") in values
    assert ("pType", "NOT_EXISTS") in values


def test_a1_medical_combo():
    conditions = _match("给我看看50岁A1医疗险客户")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("clientAge", "RANGE")].min == 50
    assert values[("clientAge", "RANGE")].max == 50
    assert values[("newValueLabel", "MATCH")] == "A1"
    assert values[("pcCategory", "CONTAINS")] == "医疗保险"


def test_vip_accident_combo():
    conditions = _match("哪些是黄金VIP意外险的人")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("vipType", "MATCH")] == "原黄金VIP"
    assert values[("pcCategory", "CONTAINS")] == "意外伤害保险"


def test_gender_plus_premium():
    conditions = _match("男性年交保费30万以上")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("clientSex", "MATCH")] == "男"
    assert values[("amPremSeg", "GTE")] == 300000


def test_age_vip_shouxian_combo():
    conditions = _match("40岁黄金VIP寿险客户")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("clientAge", "RANGE")].min == 40
    assert values[("clientAge", "RANGE")].max == 40
    assert values[("vipType", "MATCH")] == "原黄金VIP"
    assert ("productCode", "EXISTS") in values


def test_recently_not_contacted_shouxian_list():
    conditions = _match("帮我查30岁左右最近没联系寿险名单")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("clientAge", "RANGE")].min == 28
    assert values[("clientAge", "RANGE")].max == 32
    assert values[("clientTemperature", "MATCH")] == "低温"
    assert ("productCode", "EXISTS") in values


def test_kangyang_pre_member_alias():
    conditions = _match("康养预达标会员")
    assert len(conditions) == 1
    assert conditions[0].field == "kangyangClientGrade"
    assert conditions[0].value == "康养预达标会员"


def test_sum_insured_gte():
    conditions = _match("查保额超过10万的人")
    assert len(conditions) == 1
    assert conditions[0].field == "insnoSumInsSeq"
    assert conditions[0].operator.value == "GTE"
    assert conditions[0].value == 100000


def test_teacher_profession():
    conditions = _match("做老师的客户")
    assert len(conditions) == 1
    assert conditions[0].field == "profName"
    assert conditions[0].value == "老师"


def test_no_trusteeship():
    conditions = _match("哪些客户没有保单托管")
    assert len(conditions) == 1
    assert conditions[0].field == "trusteeshipFlag"
    assert conditions[0].value == "否"


def test_surname_plus_shouxian_exists():
    conditions = _match("姓张的，购买过寿险的客户")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("clientName", "MATCH")] == "张"
    assert ("productCode", "EXISTS") in values


def test_surname_plus_product():
    conditions = _match("姓张，购买过盛世金越的客户")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("clientName", "MATCH")] == "张"
    assert values[("productCode", "CONTAINS")] == "盛世金越"


def test_age_range_married_child_female_typo_query():
    conditions = _match("30-40岁的已婚有娃姓女性客户")
    values = {(c.field, c.operator.value): c.value for c in conditions}
    assert values[("clientAge", "RANGE")].min == 30
    assert values[("clientAge", "RANGE")].max == 40
    assert values[("marriSts", "MATCH")] == "已婚"
    assert values[("familyRelation", "CONTAINS")] == "子女"
    assert values[("clientSex", "MATCH")] == "女"
