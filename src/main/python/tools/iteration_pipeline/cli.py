from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from src.main.python.tools.iteration_pipeline.change_set import load_change_set, write_template
from src.main.python.tools.iteration_pipeline.config_lint import has_errors, lint_change_set
from src.main.python.tools.iteration_pipeline.evaluator import (
    EvalOptions,
    LLMJudgeOptions,
    build_expected_candidates,
    build_expected_candidates_from_config_examples,
    build_intent_label_candidates,
    build_intent_gold_from_batch_excel,
    build_skill_eval_from_batch_excel_with_llm_judge,
    build_skill_eval_from_batch_excel,
    build_label_candidates,
    check_acceptance,
    evaluate_cases,
    evaluate_intent_cases,
    evaluate_question_batch,
    evaluate_question_batch_from_config,
    load_question_batch,
    prepare_intent_review_workbook,
    write_expected_candidates,
    write_expected_candidates_excel,
    write_intent_label_candidates_excel,
    write_intent_label_candidates_jsonl,
    write_intent_gold_jsonl,
    write_label_candidates_excel,
    write_label_candidates_jsonl,
)
from src.main.python.tools.iteration_pipeline.report_writer import (
    write_batch_eval_artifacts,
    write_eval_artifacts,
    write_intent_eval_artifacts,
    write_skill_eval_artifacts,
)
from src.main.python.tools.iteration_pipeline.testset_generator import generate_cases, load_jsonl, write_jsonl


def _cmd_init(args: argparse.Namespace) -> int:
    path = write_template(args.output)
    print(f"created change set template: {path}")
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    change_set = load_change_set(args.change_set)
    messages = lint_change_set(change_set.raw)
    for message in messages:
        print(f"[{message.level}] {message.message}")
    if not messages:
        print("lint passed")
    return 1 if has_errors(messages) else 0


def _cmd_generate_testset(args: argparse.Namespace) -> int:
    change_set = load_change_set(args.change_set)
    cases = generate_cases(change_set)
    output_path = Path(args.output).resolve() if args.output else change_set.testset_path
    if not output_path:
        output_path = change_set.iteration_dir / "generated_testset.jsonl"
    write_jsonl(cases, output_path)
    print(f"generated {len(cases)} cases: {output_path}")
    return 0


async def _run_eval(args: argparse.Namespace) -> int:
    change_set = load_change_set(args.change_set)
    messages = lint_change_set(change_set.raw)
    for message in messages:
        print(f"[{message.level}] {message.message}")
    if has_errors(messages) and not args.ignore_lint_errors:
        print("lint failed; use --ignore-lint-errors to evaluate anyway")
        return 1

    testset_path = Path(args.testset).resolve() if args.testset else change_set.testset_path
    if testset_path and testset_path.exists():
        cases = load_jsonl(testset_path)
    else:
        cases = generate_cases(change_set)
        if testset_path:
            write_jsonl(cases, testset_path)

    options = EvalOptions(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        concurrency=args.concurrency,
    )
    eval_result = await evaluate_cases(cases, options)
    acceptance_failures = check_acceptance(eval_result["summary"], change_set.acceptance)
    artifacts = write_eval_artifacts(change_set, eval_result, acceptance_failures)

    print(json.dumps(eval_result["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    if acceptance_failures:
        print("acceptance failed:")
        for failure in acceptance_failures:
            print(f"- {failure}")
        return 2
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    return asyncio.run(_run_eval(args))


async def _run_batch_eval(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    cases = load_question_batch(input_path)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    graded_total = sum(1 for case in cases if "expected" in case)
    print(
        f"loaded {len(cases)} cases from {input_path} "
        f"(graded={graded_total}, ungraded={len(cases) - graded_total}, concurrency={args.concurrency})",
        flush=True,
    )
    if cases and graded_total == 0:
        print(
            "warning: no expected answers found; accuracy metrics will be N/A. "
            "This run will still report api_success_rate, condition_non_empty_rate, known_level_rate, and latency.",
            flush=True,
        )

    options = EvalOptions(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        concurrency=args.concurrency,
    )
    progress_interval = max(1, args.progress_interval)

    def print_progress(event: dict) -> None:
        completed = int(event["completed"])
        total = int(event["total"])
        if args.no_progress and completed != total:
            return
        if completed != total and completed % progress_interval != 0:
            return
        percent = (completed / total * 100) if total else 100
        status = "error" if event.get("error") else "ok"
        print(
            f"[progress] {completed}/{total} ({percent:.1f}%) "
            f"errors={event['errors']} avg_latency_ms={float(event['avg_latency_ms']):.1f} "
            f"last={event.get('case_id')} level={event.get('matched_level') or 'unknown'} {status}",
            flush=True,
        )

    eval_result = await evaluate_question_batch(cases, options, progress_callback=print_progress)

    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("src/main/python/docs/evaluations") / timestamp
        output_dir = output_dir.resolve()

    artifacts = write_batch_eval_artifacts(input_path, output_dir, eval_result)

    print(json.dumps(eval_result["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    return 1 if eval_result["summary"].get("error_count") else 0


def _cmd_batch_eval(args: argparse.Namespace) -> int:
    return asyncio.run(_run_batch_eval(args))


async def _run_intent_eval(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    cases = load_question_batch(input_path)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    graded_total = sum(
        1 for case in cases
        if case.get("expected_intent_lines") or case.get("expected_intent") or case.get("expected")
    )
    print(
        f"loaded {len(cases)} cases from {input_path} "
        f"(intent_graded={graded_total}, ungraded={len(cases) - graded_total}, concurrency={args.concurrency})",
        flush=True,
    )
    if cases and graded_total == 0:
        print(
            "warning: no expected intent answers found; intent metrics will be N/A.",
            flush=True,
        )

    options = EvalOptions(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        concurrency=args.concurrency,
    )
    eval_result = await evaluate_intent_cases(cases, options, progress_callback=_make_progress_printer(args))

    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("src/main/python/docs/evaluations") / f"intent_{timestamp}"
        output_dir = output_dir.resolve()

    artifacts = write_intent_eval_artifacts(input_path, output_dir, eval_result)
    print(json.dumps(eval_result["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    return 1 if eval_result["summary"].get("error_count") else 0


def _cmd_intent_eval(args: argparse.Namespace) -> int:
    return asyncio.run(_run_intent_eval(args))


def _make_progress_printer(args: argparse.Namespace):
    progress_interval = max(1, args.progress_interval)

    def print_progress(event: dict) -> None:
        completed = int(event["completed"])
        total = int(event["total"])
        if args.no_progress and completed != total:
            return
        if completed != total and completed % progress_interval != 0:
            return
        percent = (completed / total * 100) if total else 100
        status = "error" if event.get("error") else "ok"
        print(
            f"[progress] {completed}/{total} ({percent:.1f}%) "
            f"errors={event['errors']} avg_latency_ms={float(event['avg_latency_ms']):.1f} "
            f"last={event.get('case_id')} level={event.get('matched_level') or 'unknown'} {status}",
            flush=True,
        )

    return print_progress


def _configure_inprocess_logging(verbose: bool) -> None:
    if verbose:
        return
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")


def _expected_excel_path(jsonl_path: Path) -> Path:
    return jsonl_path.with_suffix(".xlsx")


async def _run_generate_expected(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    cases = load_question_batch(input_path)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    print(
        f"loaded {len(cases)} cases from {input_path} "
        f"(concurrency={args.concurrency})",
        flush=True,
    )

    options = EvalOptions(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        concurrency=args.concurrency,
    )
    eval_result = await evaluate_question_batch(cases, options, progress_callback=_make_progress_printer(args))
    candidates = build_expected_candidates(
        eval_result,
        include_empty_expected=args.include_empty_expected,
    )
    output_path = write_expected_candidates(candidates, args.output)
    excel_path = write_expected_candidates_excel(candidates, _expected_excel_path(output_path))

    candidate_count = sum(1 for item in candidates if item.get("label_status") == "candidate")
    manual_required_count = len(candidates) - candidate_count
    print(
        json.dumps(
            {
                "total": len(candidates),
                "candidate_expected_total": candidate_count,
                "manual_required_total": manual_required_count,
                "output": str(output_path),
                "excel": str(excel_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    print(
        "note: generated expected answers are candidates from the current parser; review them before treating them as gold labels.",
        flush=True,
    )
    return 1 if eval_result["summary"].get("error_count") else 0


def _cmd_generate_expected(args: argparse.Namespace) -> int:
    return asyncio.run(_run_generate_expected(args))


async def _run_generate_expected_from_config(args: argparse.Namespace) -> int:
    _configure_inprocess_logging(args.verbose)
    input_path = Path(args.input).resolve()
    cases = load_question_batch(input_path)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    print(
        f"loaded {len(cases)} cases from {input_path} "
        f"(mode=config_examples_exact_match, use_parser_rules={args.use_parser_rules}, concurrency={args.concurrency})",
        flush=True,
    )

    if not args.use_parser_rules:
        candidates = build_expected_candidates_from_config_examples(cases)
        output_path = write_expected_candidates(candidates, args.output)
        excel_path = write_expected_candidates_excel(candidates, _expected_excel_path(output_path))
        candidate_count = sum(1 for item in candidates if item.get("label_status") == "candidate")
        manual_required_count = len(candidates) - candidate_count
        print(
            json.dumps(
                {
                    "total": len(candidates),
                    "candidate_expected_total": candidate_count,
                    "manual_required_total": manual_required_count,
                    "output": str(output_path),
                    "excel": str(excel_path),
                    "labeling_mode": "config_examples_exact_match",
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
        print(
            "note: only exact matches from field_definitions examples/negative_examples were labeled; unmatched cases require manual labeling.",
            flush=True,
        )
        return 0

    options = EvalOptions(
        timeout_seconds=args.timeout,
        concurrency=args.concurrency,
    )
    eval_result = await evaluate_question_batch_from_config(
        cases,
        options,
        allow_l4=args.allow_l4,
        progress_callback=_make_progress_printer(args),
    )
    candidates = build_expected_candidates(
        eval_result,
        include_empty_expected=args.include_empty_expected,
        source="current_config_inprocess",
        extra_label_meta={
            "labeling_mode": "config_rules",
            "allow_l4": args.allow_l4,
        },
    )
    output_path = write_expected_candidates(candidates, args.output)
    excel_path = write_expected_candidates_excel(candidates, _expected_excel_path(output_path))

    candidate_count = sum(1 for item in candidates if item.get("label_status") == "candidate")
    manual_required_count = len(candidates) - candidate_count
    print(
        json.dumps(
            {
                "total": len(candidates),
                "candidate_expected_total": candidate_count,
                "manual_required_total": manual_required_count,
                "output": str(output_path),
                "excel": str(excel_path),
                "summary": eval_result.get("summary") or {},
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        flush=True,
    )
    print(
        "note: parser-rule labels are candidates from the current in-process parser; review them before treating them as gold labels.",
        flush=True,
    )
    return 1 if eval_result["summary"].get("error_count") else 0


def _cmd_generate_expected_from_config(args: argparse.Namespace) -> int:
    return asyncio.run(_run_generate_expected_from_config(args))


def _run_label_candidates(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    cases = load_question_batch(input_path)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    rows = build_label_candidates(cases)
    excel_path = write_label_candidates_excel(rows, args.output)
    jsonl_path = None
    if args.jsonl_output:
        jsonl_path = write_label_candidates_jsonl(rows, args.jsonl_output)
    elif args.write_jsonl:
        jsonl_path = write_label_candidates_jsonl(rows, Path(args.output).with_suffix(".jsonl"))

    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("agreement_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    result = {
        "total": len(rows),
        "excel": str(excel_path),
        "jsonl": str(jsonl_path) if jsonl_path else None,
        "agreement_status_counts": status_counts,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


def _cmd_label_candidates(args: argparse.Namespace) -> int:
    return _run_label_candidates(args)


async def _run_intent_label_candidates(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    cases = load_question_batch(input_path)
    if args.limit is not None:
        cases = cases[: max(0, args.limit)]
    print(
        f"loaded {len(cases)} cases from {input_path} "
        f"(intent candidate mode, concurrency={args.concurrency})",
        flush=True,
    )

    static_rows = build_label_candidates(cases)
    options = EvalOptions(
        base_url=args.base_url,
        timeout_seconds=args.timeout,
        concurrency=args.concurrency,
    )
    eval_result = await evaluate_question_batch(cases, options, progress_callback=_make_progress_printer(args))
    rows = build_intent_label_candidates(cases, static_rows, eval_result)

    excel_path = write_intent_label_candidates_excel(rows, args.output)
    jsonl_path = None
    if args.jsonl_output:
        jsonl_path = write_intent_label_candidates_jsonl(rows, args.jsonl_output)
    elif args.write_jsonl:
        jsonl_path = write_intent_label_candidates_jsonl(rows, Path(args.output).with_suffix(".jsonl"))

    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("review_status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    result = {
        "total": len(rows),
        "excel": str(excel_path),
        "jsonl": str(jsonl_path) if jsonl_path else None,
        "review_status_counts": status_counts,
        "api_error_count": eval_result.get("summary", {}).get("error_count", 0),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 1 if eval_result.get("summary", {}).get("error_count") else 0


def _cmd_intent_label_candidates(args: argparse.Namespace) -> int:
    return asyncio.run(_run_intent_label_candidates(args))


def _run_intent_gold_from_batch_excel(args: argparse.Namespace) -> int:
    result = build_intent_gold_from_batch_excel(
        args.input,
        sheet_name=args.sheet,
        accept_unreviewed=args.accept_unreviewed,
    )
    output_path = write_intent_gold_jsonl(result["rows"], args.output)
    skipped_path = None
    if args.skipped_output:
        skipped_path = Path(args.skipped_output).resolve()
    else:
        skipped_path = Path(args.output).resolve().with_suffix(".skipped.jsonl")
    skipped_path.parent.mkdir(parents=True, exist_ok=True)
    with skipped_path.open("w", encoding="utf-8") as file:
        for row in result["skipped"]:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            file.write("\n")

    summary = {
        **result["summary"],
        "output": str(output_path),
        "skipped_output": str(skipped_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0 if result["rows"] else 1


def _cmd_intent_gold_from_batch_excel(args: argparse.Namespace) -> int:
    return _run_intent_gold_from_batch_excel(args)


def _run_prepare_intent_review(args: argparse.Namespace) -> int:
    result = prepare_intent_review_workbook(
        args.input,
        args.output,
        sheet_name=args.sheet,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0


def _cmd_prepare_intent_review(args: argparse.Namespace) -> int:
    return _run_prepare_intent_review(args)


def _run_skill_eval(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    if args.llm_judge:
        from src.main.python.config.settings import settings

        api_key = getattr(settings, "LLM_API_KEY", "") or ""
        if args.judge_api_key_env:
            import os

            api_key = os.environ.get(args.judge_api_key_env, api_key)
        if not api_key:
            raise ValueError("missing judge API key; set LLM_API_KEY or pass --judge-api-key-env")
        skill_path = args.skill or "src/main/python/docs/eval_skills/client_search_intent_eval/SKILL.md"
        result = asyncio.run(
            build_skill_eval_from_batch_excel_with_llm_judge(
                input_path,
                sheet_name=args.sheet,
                skill_path=skill_path,
                judge_options=LLMJudgeOptions(
                    model=args.judge_model or getattr(settings, "LLM_MODEL", ""),
                    api_key=api_key,
                    base_url=args.judge_base_url or getattr(settings, "LLM_BASE_URL", None),
                    timeout_seconds=args.judge_timeout,
                    concurrency=args.judge_concurrency,
                    max_retries=args.judge_max_retries,
                ),
            )
        )
    else:
        result = build_skill_eval_from_batch_excel(
            input_path,
            sheet_name=args.sheet,
            skill_path=args.skill,
        )
    artifacts = write_skill_eval_artifacts(input_path, output_dir, result)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    return 0


def _cmd_skill_eval(args: argparse.Namespace) -> int:
    return _run_skill_eval(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iteration_pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a change_set.yaml template")
    init_parser.add_argument("--output", required=True, help="where to create change_set.yaml")
    init_parser.set_defaults(func=_cmd_init)

    lint_parser = subparsers.add_parser("lint", help="lint a change set")
    lint_parser.add_argument("--change-set", required=True)
    lint_parser.set_defaults(func=_cmd_lint)

    gen_parser = subparsers.add_parser("generate-testset", help="generate JSONL test cases from a change set")
    gen_parser.add_argument("--change-set", required=True)
    gen_parser.add_argument("--output")
    gen_parser.set_defaults(func=_cmd_generate_testset)

    eval_parser = subparsers.add_parser("eval", help="evaluate parse API with a JSONL testset")
    eval_parser.add_argument("--change-set", required=True)
    eval_parser.add_argument("--testset")
    eval_parser.add_argument("--base-url", default="http://localhost:8000")
    eval_parser.add_argument("--timeout", type=float, default=30.0)
    eval_parser.add_argument("--concurrency", type=int, default=4)
    eval_parser.add_argument("--ignore-lint-errors", action="store_true")
    eval_parser.set_defaults(func=_cmd_eval)

    run_parser = subparsers.add_parser("run", help="lint, generate testset if needed, evaluate, and write report")
    run_parser.add_argument("--change-set", required=True)
    run_parser.add_argument("--testset")
    run_parser.add_argument("--base-url", default="http://localhost:8000")
    run_parser.add_argument("--timeout", type=float, default=30.0)
    run_parser.add_argument("--concurrency", type=int, default=4)
    run_parser.add_argument("--ignore-lint-errors", action="store_true")
    run_parser.set_defaults(func=_cmd_eval)

    batch_parser = subparsers.add_parser("batch-eval", help="evaluate an ad-hoc batch of questions")
    batch_parser.add_argument("--input", required=True, help="txt/md/jsonl/csv question file")
    batch_parser.add_argument("--output-dir", help="where to write batch_eval_result.json and batch_report.md")
    batch_parser.add_argument("--base-url", default="http://localhost:8000")
    batch_parser.add_argument("--timeout", type=float, default=30.0)
    batch_parser.add_argument("--concurrency", type=int, default=4)
    batch_parser.add_argument("--limit", type=int)
    batch_parser.add_argument(
        "--progress-interval",
        type=int,
        default=10,
        help="print one progress line every N completed cases; default: 10",
    )
    batch_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="only print the final progress line before the summary",
    )
    batch_parser.set_defaults(func=_cmd_batch_eval)

    intent_eval_parser = subparsers.add_parser(
        "intent-eval",
        help="evaluate parse API by comparing generated intent summary text",
    )
    intent_eval_parser.add_argument("--input", required=True, help="jsonl/csv question file with expected_intent_lines or expected")
    intent_eval_parser.add_argument("--output-dir", help="where to write intent_eval_result.json and intent_report.md")
    intent_eval_parser.add_argument("--base-url", default="http://localhost:8000")
    intent_eval_parser.add_argument("--timeout", type=float, default=30.0)
    intent_eval_parser.add_argument("--concurrency", type=int, default=4)
    intent_eval_parser.add_argument("--limit", type=int)
    intent_eval_parser.add_argument(
        "--progress-interval",
        type=int,
        default=10,
        help="print one progress line every N completed cases; default: 10",
    )
    intent_eval_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="only print the final progress line before the summary",
    )
    intent_eval_parser.set_defaults(func=_cmd_intent_eval)

    label_parser = subparsers.add_parser(
        "generate-expected",
        help="generate candidate expected answers for an ad-hoc question batch",
    )
    label_parser.add_argument("--input", required=True, help="txt/md/jsonl/csv question file")
    label_parser.add_argument("--output", required=True, help="where to write candidate JSONL labels")
    label_parser.add_argument("--base-url", default="http://localhost:8000")
    label_parser.add_argument("--timeout", type=float, default=30.0)
    label_parser.add_argument("--concurrency", type=int, default=4)
    label_parser.add_argument("--limit", type=int)
    label_parser.add_argument(
        "--include-empty-expected",
        action="store_true",
        help="write empty expected.conditions for empty parse results; default leaves them for manual labeling",
    )
    label_parser.add_argument(
        "--progress-interval",
        type=int,
        default=10,
        help="print one progress line every N completed cases; default: 10",
    )
    label_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="only print the final progress line before the summary",
    )
    label_parser.set_defaults(func=_cmd_generate_expected)

    config_label_parser = subparsers.add_parser(
        "generate-expected-from-config",
        help="generate candidate expected answers by running the local config-based parser in-process",
    )
    config_label_parser.add_argument("--input", required=True, help="txt/md/jsonl/csv question file")
    config_label_parser.add_argument("--output", required=True, help="where to write candidate JSONL labels")
    config_label_parser.add_argument("--timeout", type=float, default=30.0)
    config_label_parser.add_argument("--concurrency", type=int, default=4)
    config_label_parser.add_argument("--limit", type=int)
    config_label_parser.add_argument(
        "--allow-l4",
        action="store_true",
        help="allow L4/LLM fallback when --use-parser-rules is enabled",
    )
    config_label_parser.add_argument(
        "--use-parser-rules",
        action="store_true",
        help="use the in-process QueryRouter/L1/L2 parser output as candidates; default only uses exact config examples",
    )
    config_label_parser.add_argument(
        "--include-empty-expected",
        action="store_true",
        help="write empty expected.conditions for empty parse results; default leaves them for manual labeling",
    )
    config_label_parser.add_argument(
        "--progress-interval",
        type=int,
        default=10,
        help="print one progress line every N completed cases; default: 10",
    )
    config_label_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="only print the final progress line before the summary",
    )
    config_label_parser.add_argument(
        "--verbose",
        action="store_true",
        help="show internal parser logs while generating labels",
    )
    config_label_parser.set_defaults(func=_cmd_generate_expected_from_config)

    label_candidates_parser = subparsers.add_parser(
        "label-candidates",
        help="generate multi-source label candidates for manual review",
    )
    label_candidates_parser.add_argument("--input", required=True, help="txt/md/jsonl/csv question file")
    label_candidates_parser.add_argument("--output", required=True, help="where to write label_candidates.xlsx")
    label_candidates_parser.add_argument("--limit", type=int)
    label_candidates_parser.add_argument("--jsonl-output", help="optional JSONL output path")
    label_candidates_parser.add_argument(
        "--write-jsonl",
        action="store_true",
        help="also write a JSONL file next to the Excel output",
    )
    label_candidates_parser.set_defaults(func=_cmd_label_candidates)

    intent_label_candidates_parser = subparsers.add_parser(
        "intent-label-candidates",
        help="generate intent-summary candidates for manual review, covering parser observations too",
    )
    intent_label_candidates_parser.add_argument("--input", required=True, help="txt/md/jsonl/csv question file")
    intent_label_candidates_parser.add_argument("--output", required=True, help="where to write intent_label_candidates.xlsx")
    intent_label_candidates_parser.add_argument("--base-url", default="http://localhost:8000")
    intent_label_candidates_parser.add_argument("--timeout", type=float, default=30.0)
    intent_label_candidates_parser.add_argument("--concurrency", type=int, default=4)
    intent_label_candidates_parser.add_argument("--limit", type=int)
    intent_label_candidates_parser.add_argument("--jsonl-output", help="optional JSONL output path")
    intent_label_candidates_parser.add_argument(
        "--write-jsonl",
        action="store_true",
        help="also write a JSONL file next to the Excel output",
    )
    intent_label_candidates_parser.add_argument(
        "--progress-interval",
        type=int,
        default=10,
        help="print one progress line every N completed cases; default: 10",
    )
    intent_label_candidates_parser.add_argument(
        "--no-progress",
        action="store_true",
        help="only print the final progress line before the summary",
    )
    intent_label_candidates_parser.set_defaults(func=_cmd_intent_label_candidates)

    intent_gold_excel_parser = subparsers.add_parser(
        "intent-gold-from-batch-excel",
        help="build intent-eval JSONL gold labels from reviewed batch_eval_result.xlsx",
    )
    intent_gold_excel_parser.add_argument("--input", required=True, help="batch_eval_result.xlsx path")
    intent_gold_excel_parser.add_argument("--output", required=True, help="where to write intent-eval JSONL")
    intent_gold_excel_parser.add_argument("--sheet", default="cases", help="sheet name to read; default: cases")
    intent_gold_excel_parser.add_argument("--skipped-output", help="optional JSONL path for skipped rows")
    intent_gold_excel_parser.add_argument(
        "--accept-unreviewed",
        action="store_true",
        help="use intent_summary as gold when review_status is blank; use carefully",
    )
    intent_gold_excel_parser.set_defaults(func=_cmd_intent_gold_from_batch_excel)

    prepare_intent_review_parser = subparsers.add_parser(
        "prepare-intent-review",
        help="add review/risk columns to batch_eval_result.xlsx for intent gold labeling",
    )
    prepare_intent_review_parser.add_argument("--input", required=True, help="batch_eval_result.xlsx path")
    prepare_intent_review_parser.add_argument("--output", required=True, help="where to write intent_review.xlsx")
    prepare_intent_review_parser.add_argument("--sheet", default="cases", help="sheet name to read; default: cases")
    prepare_intent_review_parser.set_defaults(func=_cmd_prepare_intent_review)

    skill_eval_parser = subparsers.add_parser(
        "skill-eval",
        help="prepare batch_eval_result.xlsx for evaluation with an evaluation skill rubric",
    )
    skill_eval_parser.add_argument("--input", required=True, help="batch_eval_result.xlsx path")
    skill_eval_parser.add_argument("--output-dir", required=True, help="where to write skill evaluation artifacts")
    skill_eval_parser.add_argument("--sheet", default="cases", help="sheet name to read; default: cases")
    skill_eval_parser.add_argument("--skill", help="optional SKILL.md rubric path")
    skill_eval_parser.add_argument("--llm-judge", action="store_true", help="use an OpenAI-compatible LLM judge with SKILL.md")
    skill_eval_parser.add_argument("--judge-model", help="LLM judge model; default uses settings.LLM_MODEL")
    skill_eval_parser.add_argument("--judge-base-url", help="OpenAI-compatible base URL; default uses settings.LLM_BASE_URL")
    skill_eval_parser.add_argument("--judge-api-key-env", help="environment variable containing judge API key; default uses settings.LLM_API_KEY")
    skill_eval_parser.add_argument("--judge-timeout", type=float, default=60.0, help="LLM judge request timeout seconds")
    skill_eval_parser.add_argument("--judge-concurrency", type=int, default=4, help="LLM judge concurrency")
    skill_eval_parser.add_argument("--judge-max-retries", type=int, default=2, help="LLM judge max retries per case")
    skill_eval_parser.set_defaults(func=_cmd_skill_eval)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
