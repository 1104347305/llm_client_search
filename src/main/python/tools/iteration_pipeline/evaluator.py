from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class EvalOptions:
    base_url: str = "http://localhost:8000"
    timeout_seconds: float = 30.0
    concurrency: int = 4


def _normalize_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_value(value[key]) for key in sorted(value)}
    return value


def _normalize_condition(condition: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "field": condition.get("field"),
        "operator": condition.get("operator"),
    }
    if condition.get("operator") not in {"EXISTS", "NOT_EXISTS"}:
        normalized["value"] = _normalize_value(condition.get("value"))
    return normalized


def _condition_key(condition: dict[str, Any]) -> str:
    return json.dumps(_normalize_condition(condition), ensure_ascii=False, sort_keys=True)


def compare_result(expected: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    expected_conditions = expected.get("conditions") or []
    actual_conditions = actual.get("conditions") or []
    expected_logic = expected.get("query_logic") or "AND"
    actual_logic = actual.get("query_logic") or "AND"

    expected_condition_keys = {_condition_key(item) for item in expected_conditions}
    actual_condition_keys = {_condition_key(item) for item in actual_conditions}

    missing = sorted(expected_condition_keys - actual_condition_keys)
    unexpected = sorted(actual_condition_keys - expected_condition_keys)
    exact_match = expected_logic == actual_logic and not missing and not unexpected

    expected_fields = {item.get("field") for item in expected_conditions}
    actual_fields = {item.get("field") for item in actual_conditions}
    expected_operators = {(item.get("field"), item.get("operator")) for item in expected_conditions}
    actual_operators = {(item.get("field"), item.get("operator")) for item in actual_conditions}

    return {
        "exact_match": exact_match,
        "query_logic_match": expected_logic == actual_logic,
        "field_match": expected_fields.issubset(actual_fields),
        "operator_match": expected_operators.issubset(actual_operators),
        "missing_conditions": missing,
        "unexpected_conditions": unexpected,
    }


def _extract_parse_result(response_json: dict[str, Any]) -> dict[str, Any]:
    data = response_json.get("data") or {}
    extra = data.get("extra_output_params") or {}
    if not isinstance(extra, dict):
        return {"query_logic": "AND", "conditions": []}
    return {
        "query_logic": extra.get("query_logic") or "AND",
        "conditions": extra.get("conditions") or [],
        "matched_level": extra.get("matched_level"),
        "cost_times": extra.get("cost_times"),
        "intent_summary": extra.get("intent_summary") or data.get("robot_text"),
        "matched_patterns": extra.get("matched_patterns"),
        "rewritten_query": extra.get("rewritten_query"),
    }


async def _call_parse_api(client: httpx.AsyncClient, base_url: str, query: str) -> tuple[dict[str, Any], float, str | None]:
    started = time.perf_counter()
    try:
        response = await client.post(
            f"{base_url.rstrip('/')}/api/v1/client_search_query_parse_no_encipher",
            json={
                "user_text": query,
                "user_id": "iteration_pipeline",
                "trace_id": f"iteration-{int(time.time() * 1000)}",
                "session_id": "iteration_pipeline",
                "source": "askbob",
            },
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.raise_for_status()
        return _extract_parse_result(response.json()), elapsed_ms, None
    except Exception as exc:  # noqa: BLE001 - evaluation should record every failure
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {"query_logic": "AND", "conditions": []}, elapsed_ms, str(exc)


async def evaluate_cases(cases: list[dict[str, Any]], options: EvalOptions) -> dict[str, Any]:
    semaphore = asyncio.Semaphore(max(1, options.concurrency))
    timeout = httpx.Timeout(options.timeout_seconds)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def evaluate_one(case: dict[str, Any]) -> dict[str, Any]:
            async with semaphore:
                actual, elapsed_ms, error = await _call_parse_api(client, options.base_url, str(case.get("query") or ""))
                expected = case.get("expected") or {}
                comparison = compare_result(expected, actual)
                tags = case.get("tags") or []
                is_negative = "negative" in tags or not (expected.get("conditions") or [])
                return {
                    "id": case.get("id"),
                    "query": case.get("query"),
                    "tags": tags,
                    "expected": expected,
                    "actual": actual,
                    "comparison": comparison,
                    "elapsed_ms": elapsed_ms,
                    "error": error,
                    "is_negative": is_negative,
                }

        case_results = await asyncio.gather(*(evaluate_one(case) for case in cases))

    total = len(case_results)
    exact_matches = sum(1 for item in case_results if item["comparison"]["exact_match"])
    field_matches = sum(1 for item in case_results if item["comparison"]["field_match"])
    operator_matches = sum(1 for item in case_results if item["comparison"]["operator_match"])
    positive_cases = [item for item in case_results if not item["is_negative"]]
    negative_cases = [item for item in case_results if item["is_negative"]]
    empty_positive = [
        item for item in positive_cases
        if not item["actual"].get("conditions")
    ]
    false_positive = [
        item for item in negative_cases
        if item["actual"].get("conditions")
    ]
    latencies = [item["elapsed_ms"] for item in case_results]
    level_distribution: dict[str, int] = {}
    for item in case_results:
        level = str(item["actual"].get("matched_level") or "unknown")
        level_distribution[level] = level_distribution.get(level, 0) + 1

    summary = {
        "total": total,
        "overall_accuracy": exact_matches / total if total else 0,
        "exact_match_rate": exact_matches / total if total else 0,
        "field_match_rate": field_matches / total if total else 0,
        "operator_match_rate": operator_matches / total if total else 0,
        "empty_rate": len(empty_positive) / len(positive_cases) if positive_cases else 0,
        "false_positive_rate": len(false_positive) / len(negative_cases) if negative_cases else 0,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
        "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95) - 1] if latencies else 0,
        "level_distribution": level_distribution,
        "error_count": sum(1 for item in case_results if item["error"]),
    }
    failed_cases = [item for item in case_results if not item["comparison"]["exact_match"] or item["error"]]

    return {
        "summary": summary,
        "cases": case_results,
        "failed_cases": failed_cases,
    }


def check_acceptance(summary: dict[str, Any], acceptance: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    checks = [
        ("min_overall_accuracy", "overall_accuracy", ">="),
        ("min_exact_match_rate", "exact_match_rate", ">="),
        ("max_empty_rate", "empty_rate", "<="),
        ("max_false_positive_rate", "false_positive_rate", "<="),
        ("max_avg_latency_ms", "avg_latency_ms", "<="),
        ("max_p95_latency_ms", "p95_latency_ms", "<="),
    ]
    for acceptance_key, summary_key, operator in checks:
        if acceptance_key not in acceptance:
            continue
        expected = float(acceptance[acceptance_key])
        actual = float(summary.get(summary_key) or 0)
        if operator == ">=" and actual < expected:
            failures.append(f"{summary_key}={actual:.4f} below {acceptance_key}={expected:.4f}")
        if operator == "<=" and actual > expected:
            failures.append(f"{summary_key}={actual:.4f} above {acceptance_key}={expected:.4f}")
    return failures
