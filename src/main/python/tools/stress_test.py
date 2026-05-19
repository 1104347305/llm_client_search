#!/usr/bin/env python3
"""
客户搜索 API 压测脚本

对 /api/v1/client_search_query_parse_no_encipher 接口进行并发压测，
使用指定的问题集文件逐条发送请求，统计 QPS、延迟分布、成功率等指标。

用法:
    python tools/stress_test.py                          # 默认参数
    python tools/stress_test.py -c 20 -d 60              # 20并发，持续60秒
    python tools/stress_test.py -c 10 -n 500             # 10并发，共发500个请求
    python tools/stress_test.py --url http://host:8000   # 指定目标地址
    python tools/stress_test.py --warmup 10              # 先预热10秒再压测
    python tools/stress_test.py -c 20 -d 120 --csv result.csv  # 输出CSV
"""

import argparse
import asyncio
import csv
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import httpx


# ==================== 默认配置 ====================

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_API_PATH = "/api/v1/client_search_query_parse_no_encipher"
DEFAULT_CONCURRENCY = 10
DEFAULT_DURATION_SECONDS = 60
DEFAULT_TIMEOUT = 30.0
DEFAULT_TEST_SET = Path(__file__).resolve().parents[1] / "docs" / "测试集.txt"

# ==================== 数据结构 ====================


@dataclass
class RequestResult:
    """单次请求结果"""
    index: int
    query: str
    trace_id: str
    status_code: int
    elapsed_ms: float
    success: bool
    error: str = ""
    matched_level: int = 0
    confidence: float = 0.0
    condition_count: int = 0
    response_code: int = 0  # API 返回的 code 字段


@dataclass
class StressReport:
    """压测报告"""
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_sec: float = 0.0

    # 延迟统计 (ms)
    latencies: List[float] = field(default_factory=list)

    # 按匹配层级的分布
    level_distribution: dict = field(default_factory=lambda: defaultdict(int))

    # 错误分类
    error_types: dict = field(default_factory=lambda: defaultdict(int))

    # 条件数分布
    condition_count_distribution: dict = field(default_factory=lambda: defaultdict(int))

    @property
    def qps(self) -> float:
        if self.total_duration_sec <= 0:
            return 0.0
        return self.total_requests / self.total_duration_sec

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.success_count / self.total_requests

    @property
    def avg_latency(self) -> float:
        if not self.latencies:
            return 0.0
        return sum(self.latencies) / len(self.latencies)

    @property
    def min_latency(self) -> float:
        return min(self.latencies) if self.latencies else 0.0

    @property
    def max_latency(self) -> float:
        return max(self.latencies) if self.latencies else 0.0

    def percentile(self, p: float) -> float:
        """计算第 p 百分位延迟 (0-100)"""
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * p / 100.0)
        idx = min(idx, len(sorted_lat) - 1)
        return sorted_lat[idx]


# ==================== 问题集加载 ====================


def load_queries(file_path: str) -> List[str]:
    """从测试集文件加载查询列表，跳过空行"""
    path = Path(file_path)
    if not path.exists():
        print(f"[ERROR] 测试集文件不存在: {path}")
        sys.exit(1)

    queries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                queries.append(stripped)

    print(f"[INFO] 从 {path} 加载了 {len(queries)} 条测试查询")
    return queries


# ==================== 压测执行器 ====================


class StressTester:
    def __init__(
        self,
        base_url: str,
        api_path: str,
        queries: List[str],
        concurrency: int,
        timeout: float,
        duration_sec: Optional[int] = None,
        max_requests: Optional[int] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_path = api_path
        self.url = f"{self.base_url}{self.api_path}"
        self.queries = queries
        self.concurrency = concurrency
        self.timeout = timeout
        self.duration_sec = duration_sec
        self.max_requests = max_requests

        self.results: List[RequestResult] = []
        self._semaphore = asyncio.Semaphore(concurrency)
        self._stop_event = asyncio.Event()
        self._start_time: float = 0.0
        self._request_counter = 0

    # -------- 单次请求 --------

    async def _send_one(
        self, client: httpx.AsyncClient, query: str, index: int
    ) -> RequestResult:
        trace_id = str(uuid.uuid4())[:8]
        payload = {
            "source": "askbob",
            "user_text": query,
            "session_id": f"stress-{trace_id}",
            "trace_id": trace_id,
            "user_id": "stress-test",
            "ts": int(time.time() * 1000),
            "user_action": "write",
            "action_scenario": "customerSearch",
        }

        start = time.perf_counter()
        try:
            resp = await client.post(
                self.url,
                json=payload,
                timeout=httpx.Timeout(self.timeout),
            )
            elapsed = (time.perf_counter() - start) * 1000.0

            body = {}
            try:
                body = resp.json()
            except Exception:
                pass

            api_code = body.get("code", -1)
            success = resp.status_code == 200 and api_code == 0

            data = body.get("data", {}) or {}
            extra = data.get("extra_output_params", {}) or {}

            return RequestResult(
                index=index,
                query=query,
                trace_id=trace_id,
                status_code=resp.status_code,
                elapsed_ms=elapsed,
                success=success,
                error="" if success else f"http={resp.status_code}, code={api_code}",
                matched_level=extra.get("matched_level", 0),
                confidence=extra.get("confidence", 0.0),
                condition_count=len(extra.get("conditions", [])),
                response_code=api_code,
            )
        except httpx.TimeoutException:
            elapsed = (time.perf_counter() - start) * 1000.0
            return RequestResult(
                index=index, query=query, trace_id=trace_id,
                status_code=0, elapsed_ms=elapsed, success=False, error="timeout",
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000.0
            return RequestResult(
                index=index, query=query, trace_id=trace_id,
                status_code=0, elapsed_ms=elapsed, success=False,
                error=f"{type(e).__name__}: {e}",
            )

    # -------- 工作协程 --------

    async def _worker(self, client: httpx.AsyncClient, worker_id: int):
        """每个 worker 循环取 query 发送请求"""
        query_count = len(self.queries)
        while not self._stop_event.is_set():
            if self.max_requests is not None and self._request_counter >= self.max_requests:
                break

            idx = self._request_counter % query_count
            query = self.queries[idx]

            async with self._semaphore:
                if self._stop_event.is_set():
                    break
                self._request_counter += 1
                req_idx = self._request_counter

            result = await self._send_one(client, query, req_idx)
            self.results.append(result)

    # -------- 进度报告 --------

    async def _progress_reporter(self):
        """每秒打印一次进度"""
        while not self._stop_event.is_set():
            await asyncio.sleep(1.0)
            elapsed = time.perf_counter() - self._start_time
            done = len(self.results)
            qps = done / elapsed if elapsed > 0 else 0

            # 最近1秒的结果
            recent = [r for r in self.results if r.elapsed_ms > 0][-max(1, int(qps) or 1):]
            recent_lat = sum(r.elapsed_ms for r in recent) / len(recent) if recent else 0

            ok = sum(1 for r in self.results if r.success)
            fail = done - ok

            print(
                f"\r[进度] {elapsed:5.0f}s | 已完成: {done:6d} | "
                f"QPS: {qps:6.1f} | 成功: {ok:5d} | 失败: {fail:4d} | "
                f"近1s延迟: {recent_lat:6.0f}ms",
                end="",
                flush=True,
            )

    # -------- 预热 --------

    async def warmup(self, seconds: int = 10):
        """预热：低并发跑一段时间，让服务预热"""
        print(f"\n[预热] 以 concurrency=2 预热 {seconds} 秒...")
        limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
        async with httpx.AsyncClient(limits=limits) as client:
            warmup_start = time.perf_counter()
            tasks = []
            for i in range(2):
                tasks.append(asyncio.create_task(self._warmup_worker(client, i)))
            await asyncio.sleep(seconds)
            self._stop_event.set()
            await asyncio.gather(*tasks, return_exceptions=True)

        warmup_elapsed = time.perf_counter() - warmup_start
        warmup_requests = len(self.results)
        print(
            f"[预热] 完成: {warmup_requests} 请求, "
            f"{warmup_elapsed:.1f}s, "
            f"QPS={warmup_requests / warmup_elapsed:.1f}"
        )

        # 重置计数器
        self._stop_event.clear()
        self._request_counter = 0
        self.results.clear()

    async def _warmup_worker(self, client: httpx.AsyncClient, worker_id: int):
        """预热专用 worker，低负载"""
        query_count = len(self.queries)
        while not self._stop_event.is_set():
            idx = self._request_counter % query_count
            query = self.queries[idx]
            self._request_counter += 1
            result = await self._send_one(client, query, self._request_counter)
            self.results.append(result)

    # -------- 主执行 --------

    async def run(self) -> StressReport:
        print(f"\n{'='*60}")
        print(f"压测配置")
        print(f"{'='*60}")
        print(f"  目标地址: {self.url}")
        print(f"  并发数:   {self.concurrency}")
        print(f"  测试查询: {len(self.queries)} 条")
        print(f"  超时时间: {self.timeout}s")
        if self.duration_sec:
            print(f"  持续时间: {self.duration_sec}s")
        if self.max_requests:
            print(f"  最大请求: {self.max_requests}")
        print(f"{'='*60}")

        limits = httpx.Limits(
            max_connections=self.concurrency + 10,
            max_keepalive_connections=self.concurrency,
        )

        async with httpx.AsyncClient(limits=limits) as client:
            # 启动 workers
            workers = [
                asyncio.create_task(self._worker(client, i))
                for i in range(self.concurrency)
            ]
            reporter = asyncio.create_task(self._progress_reporter())

            self._start_time = time.perf_counter()

            # 等待结束条件
            if self.duration_sec:
                await asyncio.sleep(self.duration_sec)
                self._stop_event.set()
            elif self.max_requests:
                # 等待所有 worker 完成
                while (not self._stop_event.is_set()
                       and self._request_counter < self.max_requests):
                    await asyncio.sleep(0.5)
                self._stop_event.set()

            # 收尾
            await asyncio.gather(*workers, return_exceptions=True)
            reporter.cancel()
            try:
                await reporter
            except asyncio.CancelledError:
                pass

            self._end_time = time.perf_counter()

        return self._build_report()

    def _build_report(self) -> StressReport:
        total_duration = self._end_time - self._start_time
        report = StressReport()
        report.total_requests = len(self.results)
        report.total_duration_sec = total_duration

        for r in self.results:
            if r.success:
                report.success_count += 1
            else:
                report.failure_count += 1
                report.error_types[r.error] += 1

            report.latencies.append(r.elapsed_ms)
            report.level_distribution[r.matched_level] += 1
            report.condition_count_distribution[r.condition_count] += 1

        return report


# ==================== 报告输出 ====================


def print_report(report: StressReport, results: List[RequestResult]):
    print(f"\n\n{'='*60}")
    print(f"压测报告")
    print(f"{'='*60}")

    print(f"\n--- 总览 ---")
    print(f"  总请求数:   {report.total_requests}")
    print(f"  成功:       {report.success_count} ({report.success_rate*100:.1f}%)")
    print(f"  失败:       {report.failure_count} ({(1-report.success_rate)*100:.1f}%)")
    print(f"  总耗时:     {report.total_duration_sec:.1f}s")
    print(f"  QPS:        {report.qps:.1f}")

    print(f"\n--- 延迟 (ms) ---")
    print(f"  平均:       {report.avg_latency:7.1f}")
    print(f"  最小:       {report.min_latency:7.1f}")
    print(f"  P50:        {report.percentile(50):7.1f}")
    print(f"  P90:        {report.percentile(90):7.1f}")
    print(f"  P95:        {report.percentile(95):7.1f}")
    print(f"  P99:        {report.percentile(99):7.1f}")
    print(f"  最大:       {report.max_latency:7.1f}")

    print(f"\n--- 匹配层级分布 ---")
    level_names = {0: "失败/无", 1: "L1 规则引擎", 2: "L2 增强匹配", 3: "L3 缓存", 4: "L4 LLM"}
    for level in sorted(report.level_distribution.keys()):
        count = report.level_distribution[level]
        pct = count / report.total_requests * 100 if report.total_requests else 0
        name = level_names.get(level, f"未知({level})")
        print(f"  {name:20s}: {count:5d} ({pct:5.1f}%)")

    print(f"\n--- 条件数分布 ---")
    for cnt in sorted(report.condition_count_distribution.keys()):
        count = report.condition_count_distribution[cnt]
        pct = count / report.total_requests * 100 if report.total_requests else 0
        print(f"  {cnt} 个条件: {count:5d} ({pct:5.1f}%)")

    if report.error_types:
        print(f"\n--- 错误类型 ---")
        for err, count in sorted(report.error_types.items(), key=lambda x: -x[1]):
            print(f"  {err[:80]}: {count}")

    # 打印最慢的10个请求
    print(f"\n--- 最慢的 10 个请求 ---")
    slowest = sorted(results, key=lambda r: r.elapsed_ms, reverse=True)[:10]
    for r in slowest:
        status = "OK" if r.success else f"FAIL({r.error[:30]})"
        print(
            f"  [{status}] {r.elapsed_ms:7.0f}ms | "
            f"L{r.matched_level} | "
            f"{r.query[:50]}"
        )

    # 打印一些 L4 的慢请求
    l4_results = [r for r in results if r.matched_level == 4]
    if l4_results:
        print(f"\n--- L4 请求延迟统计 ---")
        l4_lat = [r.elapsed_ms for r in l4_results]
        l4_lat.sort()
        print(f"  数量:       {len(l4_results)}")
        print(f"  平均:       {sum(l4_lat)/len(l4_lat):.0f}ms")
        print(f"  P50:        {l4_lat[len(l4_lat)//2]:.0f}ms")
        print(f"  P95:        {l4_lat[int(len(l4_lat)*0.95)]:.0f}ms")
        print(f"  P99:        {l4_lat[int(len(l4_lat)*0.99)]:.0f}ms")

    # 非 L4 请求延迟统计
    non_l4 = [r for r in results if r.matched_level != 4 and r.success]
    if non_l4:
        print(f"\n--- L1+L2 请求延迟统计 ---")
        lat = [r.elapsed_ms for r in non_l4]
        lat.sort()
        print(f"  数量:       {len(non_l4)}")
        print(f"  平均:       {sum(lat)/len(lat):.0f}ms")
        print(f"  P50:        {lat[len(lat)//2]:.0f}ms")
        print(f"  P95:        {lat[int(len(lat)*0.95)]:.0f}ms")

    print(f"\n{'='*60}\n")


def save_csv(results: List[RequestResult], filepath: str):
    """保存详细结果到 CSV"""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "index", "trace_id", "query", "success", "status_code",
            "response_code", "elapsed_ms", "matched_level", "confidence",
            "condition_count", "error",
        ])
        for r in results:
            writer.writerow([
                r.index, r.trace_id, r.query, r.success, r.status_code,
                r.response_code, f"{r.elapsed_ms:.1f}", r.matched_level,
                r.confidence, r.condition_count, r.error,
            ])
    print(f"[INFO] 详细结果已保存到: {filepath}")


def save_json(results: List[RequestResult], report: StressReport, filepath: str):
    """保存汇总结果到 JSON"""
    data = {
        "total_requests": report.total_requests,
        "success_count": report.success_count,
        "failure_count": report.failure_count,
        "success_rate": report.success_rate,
        "total_duration_sec": report.total_duration_sec,
        "qps": report.qps,
        "latency": {
            "avg": report.avg_latency,
            "min": report.min_latency,
            "p50": report.percentile(50),
            "p90": report.percentile(90),
            "p95": report.percentile(95),
            "p99": report.percentile(99),
            "max": report.max_latency,
        },
        "level_distribution": {
            str(k): v for k, v in report.level_distribution.items()
        },
        "condition_count_distribution": {
            str(k): v for k, v in report.condition_count_distribution.items()
        },
        "error_types": report.error_types,
        "details": [
            {
                "index": r.index,
                "trace_id": r.trace_id,
                "query": r.query,
                "success": r.success,
                "elapsed_ms": round(r.elapsed_ms, 1),
                "matched_level": r.matched_level,
                "condition_count": r.condition_count,
                "error": r.error,
            }
            for r in results
        ],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 汇总结果已保存到: {filepath}")


# ==================== CLI ====================


def parse_args():
    parser = argparse.ArgumentParser(
        description="客户搜索 API 压测脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s -c 10 -d 60                    # 10并发，60秒
  %(prog)s -c 20 -n 1000                  # 20并发，1000个请求
  %(prog)s -c 10 -d 120 --warmup 10       # 先预热10秒
  %(prog)s -c 5 -d 30 --csv result.csv    # 输出CSV
  %(prog)s --url http://prod:8000 -c 50 -d 300
        """,
    )
    parser.add_argument(
        "-c", "--concurrency", type=int, default=DEFAULT_CONCURRENCY,
        help=f"并发数 (默认: {DEFAULT_CONCURRENCY})",
    )
    parser.add_argument(
        "-d", "--duration", type=int, default=None,
        help=f"持续时间(秒)，与 -n 二选一 (默认: {DEFAULT_DURATION_SECONDS})",
    )
    parser.add_argument(
        "-n", "--num-requests", type=int, default=None,
        help="总请求数，与 -d 二选一",
    )
    parser.add_argument(
        "--url", type=str, default=DEFAULT_BASE_URL,
        help=f"API 基础地址 (默认: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--api-path", type=str, default=DEFAULT_API_PATH,
        help=f"API 路径 (默认: {DEFAULT_API_PATH})",
    )
    parser.add_argument(
        "-t", "--timeout", type=float, default=DEFAULT_TIMEOUT,
        help=f"单个请求超时秒数 (默认: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--testset", type=str, default=str(DEFAULT_TEST_SET),
        help=f"测试集文件路径 (默认: {DEFAULT_TEST_SET})",
    )
    parser.add_argument(
        "-w", "--warmup", type=int, default=0,
        help="预热秒数 (默认: 0, 不预热)",
    )
    parser.add_argument(
        "--csv", type=str, default=None,
        help="输出详细结果到 CSV 文件",
    )
    parser.add_argument(
        "--json", type=str, default=None,
        help="输出汇总结果到 JSON 文件",
    )
    parser.add_argument(
        "--no-progress", action="store_true",
        help="不显示实时进度",
    )
    return parser.parse_args()


async def main():
    args = parse_args()

    # 校验参数
    if args.duration is None and args.num_requests is None:
        args.duration = DEFAULT_DURATION_SECONDS

    if args.duration is not None and args.num_requests is not None:
        print("[ERROR] -d 和 -n 不能同时使用")
        sys.exit(1)

    # 加载问题集
    queries = load_queries(args.testset)

    tester = StressTester(
        base_url=args.url,
        api_path=args.api_path,
        queries=queries,
        concurrency=args.concurrency,
        timeout=args.timeout,
        duration_sec=args.duration,
        max_requests=args.num_requests,
    )

    # 预热
    if args.warmup > 0:
        await tester.warmup(seconds=args.warmup)

    # 压测
    report = await tester.run()

    # 输出报告
    print_report(report, tester.results)

    # 保存文件
    if args.csv:
        save_csv(tester.results, args.csv)
    if args.json:
        save_json(tester.results, report, args.json)


if __name__ == "__main__":
    asyncio.run(main())
