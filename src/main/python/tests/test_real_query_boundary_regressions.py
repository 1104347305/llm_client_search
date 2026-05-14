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
    return data.get("intents", [])


def _load_query_corpus():
    paths = [
        PROJECT_ROOT / "docs" / "test_questions.txt",
        PROJECT_ROOT / "docs" / "new_test_queries.txt",
    ]
    queries = set()
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                queries.add(line)
    return queries


def _find_negative_owner(query: str):
    for intent in _load_intents():
        for item in intent.get("negative_examples", []) or []:
            if item.get("query") == query:
                return intent["id"], item.get("reason", "")
    return None, ""


def _find_all_negative_owners(query: str):
    owners = []
    for intent in _load_intents():
        for item in intent.get("negative_examples", []) or []:
            if item.get("query") == query:
                owners.append((intent["id"], item.get("reason", "")))
    return owners


def test_real_boundary_queries_from_docs_are_covered_by_negative_examples():
    corpus = _load_query_corpus()

    expected_queries = {
        "被保人手机号为133XXXXXXxxx": "mobile_phone",
        "查找2018年7月投保的客户": "policy_anniversary",
        "近30天需要缴费的客户": "policy_expiry_date_lte",
        "最近投保的人": "policy_anniversary",
        "最近投保保费5000以上有哪些人": "policy_anniversary",
        "去年8月理赔的客户": "cross_sell_claim",
        "最近一个月有过医疗险理赔的客户": "cross_sell_claim",
        "找个客户有综拓理赔记录、理赔时间在2024年、险种是医疗险的": "cross_sell_claim",
    }

    for query, owner in expected_queries.items():
        assert query in corpus
        found_owner, _ = _find_negative_owner(query)
        assert found_owner == owner


def test_non_corpus_realistic_boundary_queries_are_also_covered():
    expected_queries = {
        "投保人手机号为133XXXXXXxxx": "mobile_phone",
        "联系人手机号为133XXXXXXxxx": "mobile_phone",
        "VIP开通时间在2024年的客户": "life_insurance_vip_exact",
        "安有护开通时间在2024年的客户": "zhenxiang_run_equity_grade",
        "持有臻享家医权益的客户": "zxjy_equity_grade",
        "最近一个月联系频繁的客户": "customer_temperature_gte",
        "身份证签发日期在2021年的客户": "id_valid_date_range",
    }

    for query, owner in expected_queries.items():
        found_owner, reason = _find_negative_owner(query)
        assert found_owner == owner
        assert reason


def test_total_premium_query_is_explicitly_rejected_by_wrong_numeric_fields():
    owners = _find_all_negative_owners("总保费90万以上")
    owner_ids = {owner for owner, _ in owners}

    assert "annual_premium_gte" in owner_ids
    assert "total_coverage_gte" in owner_ids
