from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from src.main.python.tools.iteration_pipeline.change_set import load_change_set, write_template
from src.main.python.tools.iteration_pipeline.config_lint import has_errors, lint_change_set
from src.main.python.tools.iteration_pipeline.evaluator import EvalOptions, check_acceptance, evaluate_cases
from src.main.python.tools.iteration_pipeline.report_writer import write_eval_artifacts
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
