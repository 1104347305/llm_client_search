import sys
from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.main.python.config.settings import settings


def _load_intents():
    path = Path(settings.FIELD_DEFINITIONS_PATH)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    intents = data.get("intents", [])
    return {intent["id"]: intent for intent in intents}


def _load_enums():
    path = Path(settings.ENUMS_DIR_PATH) / "field_enums_args.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def test_mobile_phone_has_insured_person_boundary_examples():
    intents = _load_intents()
    mobile = intents["mobile_phone"]

    negatives = {item["query"]: item["reason"] for item in mobile.get("negative_examples", [])}

    assert "被保人手机号为133XXXXXXxxx" in negatives
    assert "投保人手机号为133XXXXXXxxx" in negatives
    assert "联系人手机号为133XXXXXXxxx" in negatives


def test_client_and_family_fields_have_bidirectional_boundaries():
    intents = _load_intents()

    assert intents["name_exact"]["negative_examples"][0]["query"] == "子女叫张三的客户"
    assert intents["gender"]["negative_examples"][0]["query"] == "子女是男性的客户"
    assert intents["birthday_exact"]["negative_examples"][0]["query"] == "父母1956年出生的客户"

    family_name_negatives = {item["query"] for item in intents["family_client_name"].get("negative_examples", [])}
    family_sex_negatives = {item["query"] for item in intents["family_client_sex"].get("negative_examples", [])}
    family_age_negatives = {item["query"] for item in intents["family_client_age"].get("negative_examples", [])}
    family_birthday_negatives = {item["query"] for item in intents["family_client_birthday"].get("negative_examples", [])}

    assert "叫张三的客户" in family_name_negatives
    assert "男性客户" in family_sex_negatives
    assert "45岁以上的客户" in family_age_negatives
    assert "1990年出生的客户" in family_birthday_negatives


def test_time_fields_have_cross_field_boundary_examples():
    intents = _load_intents()

    expiry_range_negatives = {item["query"] for item in intents["policy_expiry_date_range"].get("negative_examples", [])}
    expiry_lte_negatives = {item["query"] for item in intents["policy_expiry_date_lte"].get("negative_examples", [])}
    pay_end_negatives = {item["query"] for item in intents["eff_app_end_date"].get("negative_examples", [])}
    anniversary_negatives = {item["query"] for item in intents["policy_anniversary"].get("negative_examples", [])}
    id_valid_negatives = {item["query"] for item in intents["id_valid_date_range"].get("negative_examples", [])}

    assert "本月缴费期满的客户" in expiry_range_negatives
    assert "证件即将到期的客户" in expiry_range_negatives
    assert "近30天需要缴费的客户" in expiry_lte_negatives
    assert "30天内寿险到期的客户" in pay_end_negatives
    assert "2018年7月投保的客户" in anniversary_negatives
    assert "身份证签发日期在2021年的客户" in id_valid_negatives


def test_status_and_existence_fields_have_boundary_examples():
    intents = _load_intents()

    value_negatives = {item["query"] for item in intents["customer_value_exact"].get("negative_examples", [])}
    temp_negatives = {item["query"] for item in intents["customer_temperature_gte"].get("negative_examples", [])}
    vip_negatives = {item["query"] for item in intents["life_insurance_vip_exact"].get("negative_examples", [])}
    zxjy_negatives = {item["query"] for item in intents["zxjy_equity_grade"].get("negative_examples", [])}
    zhenxiang_negatives = {item["query"] for item in intents["zhenxiang_run_equity_grade"].get("negative_examples", [])}

    assert "年缴保费10万以上的客户" in value_negatives
    assert "最近一个月联系频繁的客户" in temp_negatives
    assert "VIP开通时间在2024年的客户" in vip_negatives
    assert "持有臻享家医权益的客户" in zxjy_negatives
    assert "安有护开通时间在2024年的客户" in zhenxiang_negatives


def test_grade_range_intents_are_split_from_exact_intents():
    intents = _load_intents()

    assert "jujia_client_grade_range" in intents
    assert "kangyang_client_grade_range" in intents

    jujia_exact_queries = {item["query"] for item in intents["jujia_client_grade_exact"].get("examples", [])}
    kangyang_exact_queries = {item["query"] for item in intents["kangyang_client_grade_exact"].get("examples", [])}

    assert "居家v2及以上的客户" not in jujia_exact_queries
    assert "康养会员客户" not in kangyang_exact_queries


def test_pc_category_covers_generic_accident_insurance_queries():
    intents = _load_intents()
    held_product_category = intents["held_product_category"]

    retrieval_text = held_product_category.get("retrieval_text", "")
    example_queries = {item["query"] for item in held_product_category.get("examples", [])}

    assert "未购买意外险" in retrieval_text
    assert "买了车险但没买意外险" in retrieval_text
    assert "买了车险，但没有购买意外险的客户" in example_queries


def test_g_product_code_rejects_generic_accident_insurance_queries():
    intents = _load_intents()
    g_product_negatives = {item["query"] for item in intents["g_product_code"].get("negative_examples", [])}

    assert "买了车险，但没有购买意外险的客户" in g_product_negatives


def test_life_insurance_exists_and_not_exists_are_defined_as_generic_intents():
    intents = _load_intents()

    life_exists = intents["life_insurance_product_exists"]
    life_not_exists = intents["life_insurance_product_not_exists"]

    exists_queries = {item["query"] for item in life_exists.get("examples", [])}
    not_exists_queries = {item["query"] for item in life_not_exists.get("examples", [])}

    assert life_exists["operator"] == "EXISTS"
    assert "寿险客户" in exists_queries
    assert life_not_exists["operator"] == "NOT_EXISTS"
    assert "不是寿险客户" in not_exists_queries


def test_has_property_insurance_is_defined_but_unsupported():
    intents = _load_intents()

    intent = intents["has_property_insurance"]

    assert intent["is_supported"] is False
    assert intent["field"] == "isBuyPregnancy"
    assert intent["enum_ref"] == "isBuyPregnancy"

    enums = _load_enums()
    assert enums["isBuyPregnancy"]["values"] == ["是", "否"]


def test_relative_date_and_overdue_payment_intents_are_separated():
    intents = _load_intents()

    assert intents["policy_expiry_date_range_relative"]["operator"] == "RANGE"
    assert intents["eff_app_end_date_lte"]["operator"] == "LTE"

    expiry_queries = {item["query"] for item in intents["policy_expiry_date_range_relative"].get("examples", [])}
    overdue_queries = {item["query"] for item in intents["eff_app_end_date_lte"].get("examples", [])}

    assert "未来一个月即将到期的客户（当前2026-03-25）" in expiry_queries
    assert "客户缴费期已满（当前2026-03-25）" in overdue_queries


def test_held_product_type_exists_intents_are_split_from_match_intent():
    intents = _load_intents()

    assert intents["held_product_type"]["operator"] == "MATCH"
    assert intents["held_product_type_exists"]["operator"] == "EXISTS"
    assert intents["held_product_type_not_exists"]["operator"] == "NOT_EXISTS"

    match_queries = {item["query"] for item in intents["held_product_type"].get("examples", [])}
    exists_queries = {item["query"] for item in intents["held_product_type_exists"].get("examples", [])}
    not_exists_queries = {item["query"] for item in intents["held_product_type_not_exists"].get("examples", [])}

    assert "买了保险的客户" not in match_queries
    assert "买了保险的客户" in exists_queries
    assert "没有买保险的客户" in not_exists_queries


def test_customer_value_group_is_split_from_exact_intent():
    intents = _load_intents()

    assert intents["customer_value_exact"]["operator"] == "MATCH"
    assert intents["customer_value_group"]["operator"] == "CONTAINS"

    exact_queries = {item["query"] for item in intents["customer_value_exact"].get("examples", [])}
    group_queries = {item["query"] for item in intents["customer_value_group"].get("examples", [])}

    assert "A类客户" not in exact_queries
    assert "AB类客户" in group_queries


def test_vip_and_equity_exists_intents_are_split_from_exact_match():
    intents = _load_intents()

    assert intents["life_insurance_vip_exact"]["operator"] == "CONTAINS"
    assert intents["life_insurance_vip_exists"]["operator"] == "EXISTS"
    assert intents["life_insurance_vip_not_exists"]["operator"] == "NOT_EXISTS"
    assert intents["zhenxiang_run_equity_grade"]["operator"] == "MATCH"
    assert intents["zhenxiang_run_equity_exists"]["operator"] == "EXISTS"

    vip_exists_queries = {item["query"] for item in intents["life_insurance_vip_exists"].get("examples", [])}
    vip_not_exists_queries = {item["query"] for item in intents["life_insurance_vip_not_exists"].get("examples", [])}
    equity_exists_queries = {item["query"] for item in intents["zhenxiang_run_equity_exists"].get("examples", [])}

    assert "寿险VIP客户" in vip_exists_queries
    assert "不是寿险VIP的客户" in vip_not_exists_queries
    assert "持有安有护权益的客户" in equity_exists_queries


def test_operator_coverage_baselines_for_key_field_types():
    intents = _load_intents()

    by_field = {}
    for intent in intents.values():
        by_field.setdefault(intent["field"], set()).add(intent["operator"])

    assert {"GTE", "LTE", "RANGE", "EXISTS", "NOT_EXISTS"} <= by_field["clientAge"]
    assert {"GTE", "LTE", "RANGE", "EXISTS", "NOT_EXISTS"} <= by_field["clientBirthday"]
    assert {"CONTAINS", "NOT_CONTAINS", "EXISTS", "NOT_EXISTS"} <= by_field["pCategorys"]
    assert {"CONTAINS", "EXISTS", "NOT_EXISTS"} <= by_field["vipType"]
    assert {"RANGE", "LTE", "EXISTS", "NOT_EXISTS"} <= by_field["validSinsMatuDateTime"]
    assert {"GTE", "LTE", "RANGE", "EXISTS", "NOT_EXISTS"} <= by_field["effAppEndDate"]
