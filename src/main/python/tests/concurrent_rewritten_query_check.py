"""
并发检查 QueryRouter 的 rewritten_query / matched_patterns 是否串请求。

默认只压 L2：脚本会临时关闭 L4，避免没命中 L2 的样本误打模型接口。

用法：
  /Users/mickey/anaconda3/bin/python src/main/python/tests/concurrent_rewritten_query_check.py
  /Users/mickey/anaconda3/bin/python src/main/python/tests/concurrent_rewritten_query_check.py --concurrency 50 --rounds 20
  /Users/mickey/anaconda3/bin/python src/main/python/tests/concurrent_rewritten_query_check.py --queries-file /path/to/queries.txt
"""
from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.modules.setdefault("redis", types.ModuleType("redis"))

from src.main.python.config.settings import settings
from src.main.python.steps.query_router import QueryRouter
from loguru import logger


DEFAULT_QUERIES = [
    "A类客户",
    "高温客户",
    "中高温客户",
    "高温A类客户",
    "A类中高温客户",
    "客户价值B以上的客户",
    "客户价值B及以上的客户",
    "有买养老险的客户",
    "有买健康险的客户",
    "有买产险的客户",
    "买过保险的客户",
    "未配置养老险的客户",
]


@dataclass
class CheckResult:
    query: str
    expected_rewritten_query: str
    actual_rewritten_query: str | None
    matched_level: int
    elapsed_ms: float
    errors: list[str]


def _load_queries(path: str | None) -> list[str]:
    if not path:
        return list(DEFAULT_QUERIES)

    lines = Path(path).read_text(encoding="utf-8").splitlines()
    queries = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    if not queries:
        raise ValueError(f"queries file is empty: {path}")
    return queries


def _expected_rewritten_query(router: QueryRouter, query: str) -> str:
    compact = query.replace(" ", "").replace("。", "")
    return router.field_registry.normalize_query(compact)


def _matched_text_errors(
    query: str,
    expected_rewritten_query: str,
    matched_patterns: list[dict[str, Any]] | None,
) -> list[str]:
    errors: list[str] = []
    for idx, item in enumerate(matched_patterns or []):
        matched_text = item.get("matched_text")
        if matched_text is None:
            continue
        matched_text = str(matched_text)
        if matched_text and matched_text not in expected_rewritten_query:
            errors.append(
                f"matched_patterns[{idx}].matched_text={matched_text!r} "
                f"not in own rewritten_query for query={query!r}"
            )
    return errors


async def _check_one(router: QueryRouter, query: str, require_l2: bool) -> CheckResult:
    expected = _expected_rewritten_query(router, query)
    start = time.perf_counter()
    parsed = await router.route_with_peeling(query)
    elapsed_ms = (time.perf_counter() - start) * 1000

    errors: list[str] = []
    if parsed.rewritten_query != expected:
        errors.append(
            f"rewritten_query mismatch: expected={expected!r}, actual={parsed.rewritten_query!r}"
        )

    if require_l2 and parsed.matched_level != 2:
        errors.append(f"expected L2 matched_level=2, actual={parsed.matched_level}")

    errors.extend(_matched_text_errors(query, expected, parsed.matched_patterns))

    return CheckResult(
        query=query,
        expected_rewritten_query=expected,
        actual_rewritten_query=parsed.rewritten_query,
        matched_level=parsed.matched_level,
        elapsed_ms=elapsed_ms,
        errors=errors,
    )


async def _run(args: argparse.Namespace) -> int:
    logger.remove()
    logger.add(sys.stderr, level=args.log_level)

    queries = _load_queries(args.queries_file)
    if args.shuffle:
        random.shuffle(queries)

    if args.disable_l4:
        settings.ENABLE_L4 = False

    print("初始化 QueryRouter ...")
    started = time.perf_counter()
    router = QueryRouter()
    print(f"初始化完成，耗时 {(time.perf_counter() - started):.2f}s")

    print("预热并校验样本是否可用于本次压测 ...")
    warmup_results = [await _check_one(router, query, args.require_l2) for query in queries]
    warmup_errors = [result for result in warmup_results if result.errors]
    if warmup_errors and not args.ignore_warmup_errors:
        print("预热失败，以下查询不适合作为本次 L2 并发样本：")
        for result in warmup_errors:
            print(f"- {result.query}: {'; '.join(result.errors)}")
        print("可调整 queries-file，或加 --ignore-warmup-errors 继续压测。")
        return 2

    cases = [(round_idx, query) for round_idx in range(args.rounds) for query in queries]
    if args.shuffle:
        random.shuffle(cases)

    semaphore = asyncio.Semaphore(args.concurrency)

    async def guarded_check(round_idx: int, query: str) -> CheckResult:
        async with semaphore:
            return await _check_one(router, query, args.require_l2)

    print(
        f"开始并发检查：queries={len(queries)}, rounds={args.rounds}, "
        f"total={len(cases)}, concurrency={args.concurrency}, disable_l4={args.disable_l4}"
    )
    started = time.perf_counter()
    results = await asyncio.gather(*(guarded_check(round_idx, query) for round_idx, query in cases))
    total_elapsed = time.perf_counter() - started

    failed = [result for result in results if result.errors]
    elapsed_values = [result.elapsed_ms for result in results]
    p95 = statistics.quantiles(elapsed_values, n=20)[18] if len(elapsed_values) >= 20 else max(elapsed_values)
    p99 = statistics.quantiles(elapsed_values, n=100)[98] if len(elapsed_values) >= 100 else max(elapsed_values)

    print(
        f"完成：total={len(results)}, failed={len(failed)}, "
        f"wall_time={total_elapsed:.2f}s, avg={statistics.mean(elapsed_values):.2f}ms, "
        f"p95={p95:.2f}ms, p99={p99:.2f}ms"
    )

    if failed:
        print("发现疑似串请求/异常结果：")
        for result in failed[: args.max_failures]:
            print(
                f"- query={result.query!r}, expected={result.expected_rewritten_query!r}, "
                f"actual={result.actual_rewritten_query!r}, level={result.matched_level}, "
                f"errors={'; '.join(result.errors)}"
            )
        if len(failed) > args.max_failures:
            print(f"... 还有 {len(failed) - args.max_failures} 条失败未展示")
        return 1

    print("未发现 rewritten_query / matched_patterns 串请求。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="并发检查 QueryRouter 请求级状态是否串请求")
    parser.add_argument("--concurrency", type=int, default=30, help="并发数")
    parser.add_argument("--rounds", type=int, default=10, help="每条 query 重复轮数")
    parser.add_argument("--queries-file", default=None, help="自定义 query 文件，每行一条")
    parser.add_argument("--shuffle", action="store_true", help="打乱 query 顺序")
    parser.add_argument("--disable-l4", action="store_true", default=True, help="压测时关闭 L4，默认开启")
    parser.add_argument("--allow-l4", dest="disable_l4", action="store_false", help="允许没命中 L2 时走 L4")
    parser.add_argument("--require-l2", action="store_true", default=True, help="要求样本必须命中 L2，默认开启")
    parser.add_argument("--allow-non-l2", dest="require_l2", action="store_false", help="允许非 L2 结果")
    parser.add_argument("--ignore-warmup-errors", action="store_true", help="预热有错误也继续压测")
    parser.add_argument("--max-failures", type=int, default=20, help="最多打印多少条失败")
    parser.add_argument("--log-level", default="ERROR", help="脚本运行日志级别，默认 ERROR")
    args = parser.parse_args()

    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
