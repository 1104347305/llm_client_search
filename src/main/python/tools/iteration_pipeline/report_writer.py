from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.main.python.tools.iteration_pipeline.change_set import ChangeSet


def write_eval_artifacts(change_set: ChangeSet, eval_result: dict[str, Any], acceptance_failures: list[str]) -> dict[str, Path]:
    output_dir = change_set.iteration_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    eval_path = output_dir / "eval_result.json"
    failed_path = output_dir / "failed_cases.jsonl"
    report_path = output_dir / "report.md"

    eval_path.write_text(
        json.dumps(eval_result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with failed_path.open("w", encoding="utf-8") as file:
        for case in eval_result.get("failed_cases") or []:
            file.write(json.dumps(case, ensure_ascii=False, sort_keys=True))
            file.write("\n")

    report_path.write_text(
        render_report(change_set, eval_result, acceptance_failures),
        encoding="utf-8",
    )
    return {
        "eval_result": eval_path,
        "failed_cases": failed_path,
        "report": report_path,
    }


def _format_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_report(change_set: ChangeSet, eval_result: dict[str, Any], acceptance_failures: list[str]) -> str:
    summary = eval_result.get("summary") or {}
    failed_cases = eval_result.get("failed_cases") or []
    passed = not acceptance_failures
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"# {change_set.id} 自动化迭代报告",
        "",
        f"生成时间：{generated_at}",
        "",
        "## 结论",
        "",
        f"- 是否通过验收：{'是' if passed else '否'}",
        f"- 样本总数：{summary.get('total', 0)}",
        f"- 整体准确率：{_format_percent(float(summary.get('overall_accuracy', summary.get('exact_match_rate')) or 0))}",
        f"- exact_match_rate：{_format_percent(float(summary.get('exact_match_rate') or 0))}",
        f"- field_match_rate：{_format_percent(float(summary.get('field_match_rate') or 0))}",
        f"- operator_match_rate：{_format_percent(float(summary.get('operator_match_rate') or 0))}",
        f"- empty_rate：{_format_percent(float(summary.get('empty_rate') or 0))}",
        f"- false_positive_rate：{_format_percent(float(summary.get('false_positive_rate') or 0))}",
        f"- avg_latency_ms：{float(summary.get('avg_latency_ms') or 0):.2f}",
        f"- p95_latency_ms：{float(summary.get('p95_latency_ms') or 0):.2f}",
        f"- error_count：{summary.get('error_count', 0)}",
        "",
        "## 本次变更",
        "",
        f"- 标题：{change_set.title}",
        f"- owner：{change_set.owner or ''}",
        f"- 字段数：{len(change_set.fields)}",
        f"- 枚举数：{len(change_set.enums)}",
        f"- value mapping 字段数：{len(change_set.value_mappings)}",
        f"- L2 规则数：{len(change_set.l2_rules)}",
        "",
        "## 层级分布",
        "",
        "| matched_level | 数量 |",
        "| --- | --- |",
    ]

    for level, count in sorted((summary.get("level_distribution") or {}).items()):
        lines.append(f"| {level} | {count} |")

    lines.extend(["", "## 验收失败项", ""])
    if acceptance_failures:
        lines.extend(f"- {item}" for item in acceptance_failures)
    else:
        lines.append("- 无")

    lines.extend(
        [
            "",
            "## 失败样本",
            "",
            "| id | query | 归因 |",
            "| --- | --- | --- |",
        ]
    )
    if failed_cases:
        for item in failed_cases[:50]:
            reason = _guess_failure_reason(item)
            query = str(item.get("query") or "").replace("|", "\\|")
            lines.append(f"| {item.get('id')} | {query} | {reason} |")
    else:
        lines.append("| - | - | 无 |")

    lines.extend(
        [
            "",
            "## 下一轮行动",
            "",
            "- [ ] 查看 failed_cases.jsonl 中的失败样本。",
            "- [ ] 对 field_not_recalled 补 retrieval_text/examples 后重建字段索引。",
            "- [ ] 对 l2_false_positive 收紧 enhanced_rules 正则上下文。",
            "- [ ] 对 enum_not_normalized 补 value_mappings 或枚举值。",
        ]
    )
    return "\n".join(lines) + "\n"


def _guess_failure_reason(case: dict[str, Any]) -> str:
    if case.get("error"):
        return "api_error"
    comparison = case.get("comparison") or {}
    actual = case.get("actual") or {}
    expected = case.get("expected") or {}
    if expected.get("conditions") and not actual.get("conditions"):
        return "empty_result_or_field_not_recalled"
    if not expected.get("conditions") and actual.get("conditions"):
        return "false_positive"
    if comparison.get("missing_conditions"):
        return "condition_missing_or_value_wrong"
    if comparison.get("unexpected_conditions"):
        return "unexpected_condition"
    if not comparison.get("query_logic_match"):
        return "logic_wrong"
    return "unknown"
