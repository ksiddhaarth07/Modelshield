#!/usr/bin/env python3
"""ModelShield 100-ticket live benchmark.

Replays ``eval/dataset_100_tickets.json`` against one or both deployed stacks
with a strict per-stack concurrency cap, then computes accuracy, P1 recall,
p95 latency, exact Bedrock spend, GB-seconds and the frontier-token delta.

Usage
-----
    python eval/run_benchmark.py --validate-only
    python eval/run_benchmark.py --v1-url https://... --v2-url https://... \
        --out eval/results/benchmark_report.json

The runner never guesses: a request that does not return HTTP 200 and a valid
ModelShield body is counted as a miss, not silently dropped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

SEVERITIES = ("P1", "P2", "P3", "P4")
CATEGORIES = ("incident", "security", "billing", "account", "how_to", "bug")

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVAL_DIR / "dataset_100_tickets.json"
DEFAULT_OUT = EVAL_DIR / "results" / "benchmark_report.json"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------
def load_dataset(path: Path) -> Dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    tickets = raw.get("tickets")
    if not isinstance(tickets, list):
        raise ValueError("dataset must contain a 'tickets' list")

    seen = set()
    for index, ticket in enumerate(tickets):
        where = f"ticket #{index + 1}"
        if not isinstance(ticket, dict):
            raise ValueError(f"{where} is not an object")
        ticket_id = ticket.get("ticket_id")
        if not isinstance(ticket_id, str) or not ticket_id.strip():
            raise ValueError(f"{where} has no ticket_id")
        if ticket_id in seen:
            raise ValueError(f"duplicate ticket_id {ticket_id}")
        seen.add(ticket_id)
        if not isinstance(ticket.get("subject"), str) or not ticket["subject"].strip():
            raise ValueError(f"{ticket_id} has no subject")
        if not isinstance(ticket.get("body"), str) or len(ticket["body"].strip()) < 10:
            raise ValueError(f"{ticket_id} body is too short")

        truth = ticket.get("ground_truth")
        if not isinstance(truth, dict):
            raise ValueError(f"{ticket_id} has no ground_truth")
        if truth.get("severity") not in SEVERITIES:
            raise ValueError(f"{ticket_id} has invalid ground-truth severity")
        if truth.get("category") not in CATEGORIES:
            raise ValueError(f"{ticket_id} has invalid ground-truth category")

    raw["tickets"] = tickets
    return raw


def distribution(tickets: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    severities = Counter(t["ground_truth"]["severity"] for t in tickets)
    categories = Counter(t["ground_truth"]["category"] for t in tickets)
    return {
        "tickets": len(tickets),
        "by_severity": {key: severities.get(key, 0) for key in SEVERITIES},
        "by_category": {key: categories.get(key, 0) for key in CATEGORIES},
    }


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile (p95 uses pct=95)."""

    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * (pct / 100.0)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def reduction_pct(before: float, after: float) -> Optional[float]:
    if not before:
        return None
    return round(100.0 * (1.0 - (after / before)), 2)


# ---------------------------------------------------------------------------
# HTTP replay
# ---------------------------------------------------------------------------
async def _post_once(
    client: httpx.AsyncClient,
    url: str,
    payload: Dict[str, str],
    semaphore: asyncio.Semaphore,
    timeout: float,
    pacer: "Pacer",
) -> Tuple[Optional[httpx.Response], Optional[str]]:
    async with semaphore:
        await pacer.wait()
        try:
            response = await client.post(url, json=payload, timeout=timeout)
            return response, None
        except httpx.HTTPError as exc:
            return None, f"{type(exc).__name__}: {exc}"


class Pacer:
    """Spaces request starts to stay under the Bedrock per-minute quota."""

    def __init__(self, min_interval: float) -> None:
        self._interval = max(0.0, min_interval)
        self._lock = asyncio.Lock()
        self._next = 0.0

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._interval
        if delay > 0:
            await asyncio.sleep(delay)


def _empty_record(ticket: Dict[str, Any], status: Optional[int], error: str) -> Dict[str, Any]:
    return {
        "ticket_id": ticket["ticket_id"],
        "ground_truth": dict(ticket["ground_truth"]),
        "prediction": None,
        "telemetry": None,
        "http_status": status,
        "error": error,
        "correct": False,
        "severity_correct": False,
        "category_correct": False,
    }


def _build_record(ticket: Dict[str, Any], response: httpx.Response) -> Dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return _empty_record(ticket, response.status_code, "response body is not JSON")
    if not isinstance(body, dict):
        return _empty_record(ticket, response.status_code, "response body is not a JSON object")

    prediction = {
        "severity": body.get("severity"),
        "category": body.get("category"),
        "confidence": body.get("confidence"),
    }
    if prediction["severity"] not in SEVERITIES or prediction["category"] not in CATEGORIES:
        return _empty_record(ticket, response.status_code, "response does not match triage contract")

    truth = ticket["ground_truth"]
    severity_correct = prediction["severity"] == truth["severity"]
    category_correct = prediction["category"] == truth["category"]
    return {
        "ticket_id": ticket["ticket_id"],
        "ground_truth": dict(truth),
        "prediction": prediction,
        "telemetry": body.get("telemetry") or {},
        "http_status": response.status_code,
        "error": None,
        "correct": bool(severity_correct and category_correct),
        "severity_correct": bool(severity_correct),
        "category_correct": bool(category_correct),
    }


async def run_ticket(
    client: httpx.AsyncClient,
    endpoint: str,
    ticket: Dict[str, Any],
    semaphore: asyncio.Semaphore,
    timeout: float,
    attempts: int,
    pacer: Pacer,
) -> Dict[str, Any]:
    payload = {
        "ticket_id": ticket["ticket_id"],
        "subject": ticket["subject"],
        "body": ticket["body"],
    }

    last_error = "request never executed"
    last_status: Optional[int] = None

    for attempt in range(1, attempts + 1):
        response, transport_error = await _post_once(
            client, endpoint, payload, semaphore, timeout, pacer
        )
        if response is None:
            last_error = transport_error or "transport error"
            last_status = None
        elif response.status_code == 200:
            return _build_record(ticket, response)
        elif 400 <= response.status_code < 500:
            # Client errors are deterministic; retrying only burns time.
            return _empty_record(ticket, response.status_code, f"HTTP {response.status_code}: {response.text[:200]}")
        else:
            last_status = response.status_code
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"

        if attempt < attempts:
            await asyncio.sleep(0.5 * attempt)

    return _empty_record(ticket, last_status, last_error)


async def healthcheck(client: httpx.AsyncClient, base_url: str) -> Optional[Dict[str, Any]]:
    try:
        response = await client.get(f"{base_url}/health", timeout=10.0)
        if response.status_code == 200:
            return response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return None


async def run_stack(
    name: str,
    base_url: str,
    tickets: Sequence[Dict[str, Any]],
    concurrency: int,
    timeout: float,
    attempts: int,
    pacing: float,
) -> Dict[str, Any]:
    base_url = base_url.rstrip("/")
    endpoint = f"{base_url}/triage"
    semaphore = asyncio.Semaphore(concurrency)
    pacer = Pacer(pacing)
    limits = httpx.Limits(
        max_connections=concurrency, max_keepalive_connections=concurrency
    )

    client_headers: Dict[str, str] = {"Content-Type": "application/json"}
    auth_token = os.environ.get("MODELSHIELD_AUTH_TOKEN", "").strip()
    if auth_token:
        client_headers["Authorization"] = f"Bearer {auth_token}"

    async with httpx.AsyncClient(
        limits=limits,
        timeout=timeout,
        headers=client_headers,
    ) as client:
        health = await healthcheck(client, base_url)
        if health is None:
            raise RuntimeError(
                f"{name}: GET /health failed for {base_url}; refusing to spend 100 triage calls"
            )

        started = time.perf_counter()
        tasks = [
            asyncio.ensure_future(
                run_ticket(client, endpoint, ticket, semaphore, timeout, attempts, pacer)
            )
            for ticket in tickets
        ]

        records: List[Dict[str, Any]] = []
        for completed, future in enumerate(asyncio.as_completed(tasks), start=1):
            records.append(await future)
            if completed % 10 == 0 or completed == len(tasks):
                print(f"  {name}: {completed}/{len(tasks)} requests complete", flush=True)

        wall_seconds = time.perf_counter() - started

    order = {ticket["ticket_id"]: index for index, ticket in enumerate(tickets)}
    records.sort(key=lambda record: order[record["ticket_id"]])

    return {
        "name": name,
        "api_url": base_url,
        "health": health,
        "wall_clock_seconds": round(wall_seconds, 2),
        "metrics": summarize(records),
        "records": records,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def summarize(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    ok = [r for r in records if r["http_status"] == 200]
    correct = [r for r in records if r["correct"]]

    truth_p1 = [r for r in records if r["ground_truth"]["severity"] == "P1"]
    p1_hits = [r for r in truth_p1 if r["severity_correct"]]
    predicted_p1 = [
        r for r in ok if (r["prediction"] or {}).get("severity") == "P1"
    ]
    p1_true_positive = [r for r in predicted_p1 if r["ground_truth"]["severity"] == "P1"]

    telemetry = [r["telemetry"] for r in ok if isinstance(r["telemetry"], dict)]
    latencies = [float(t.get("latency_ms") or 0) for t in telemetry]
    total_cost = sum(float(t.get("estimated_cost_usd") or 0) for t in telemetry)
    total_gb_seconds = sum(float(t.get("lambda_gb_seconds") or 0) for t in telemetry)
    total_frontier_tokens = sum(int(t.get("frontier_tokens_used") or 0) for t in telemetry)

    routes = Counter(str(t.get("route_decision") or "unknown") for t in telemetry)

    accuracy = (len(correct) / total) if total else 0.0
    accuracy_on_success = (len(correct) / len(ok)) if ok else 0.0

    return {
        "requests": total,
        "successful_requests": len(ok),
        "failed_requests": total - len(ok),
        "correct": len(correct),
        "accuracy": round(accuracy, 4),
        "accuracy_on_successful": round(accuracy_on_success, 4),
        "severity_accuracy": round(sum(1 for r in records if r["severity_correct"]) / total, 4) if total else 0.0,
        "category_accuracy": round(sum(1 for r in records if r["category_correct"]) / total, 4) if total else 0.0,
        "p1_total": len(truth_p1),
        "p1_recall": round(len(p1_hits) / len(truth_p1), 4) if truth_p1 else None,
        "p1_precision": round(len(p1_true_positive) / len(predicted_p1), 4) if predicted_p1 else None,
        "p95_latency_ms": round(percentile(latencies, 95), 1),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
        "total_cost_usd": round(total_cost, 8),
        "avg_cost_usd": round(total_cost / total, 10) if total else 0.0,
        "cost_per_successful_ticket_usd": round(total_cost / len(correct), 8) if correct else None,
        "cost_per_10k_tickets_usd": round(total_cost / total * 10_000, 4) if total else 0.0,
        "total_frontier_tokens": total_frontier_tokens,
        "total_lambda_gb_seconds": round(total_gb_seconds, 4),
        "cache_hits": sum(1 for t in telemetry if t.get("cache_hit")),
        "escalations": sum(1 for t in telemetry if t.get("escalated")),
        "fallbacks": sum(1 for t in telemetry if t.get("fallback_triggered")),
        "route_decisions": dict(sorted(routes.items())),
    }


def compare(v1: Dict[str, Any], v2: Dict[str, Any]) -> Dict[str, Any]:
    a, b = v1["metrics"], v2["metrics"]
    return {
        "cost_per_10k_reduction_pct": reduction_pct(
            a["cost_per_10k_tickets_usd"], b["cost_per_10k_tickets_usd"]
        ),
        "p95_latency_reduction_pct": reduction_pct(a["p95_latency_ms"], b["p95_latency_ms"]),
        "frontier_tokens_avoided_pct": reduction_pct(
            a["total_frontier_tokens"], b["total_frontier_tokens"]
        ),
        "lambda_gb_seconds_reduction_pct": reduction_pct(
            a["total_lambda_gb_seconds"], b["total_lambda_gb_seconds"]
        ),
        "accuracy_delta_pp": round((b["accuracy"] - a["accuracy"]) * 100, 2),
        "p1_recall_delta_pp": (
            round((b["p1_recall"] - a["p1_recall"]) * 100, 2)
            if a["p1_recall"] is not None and b["p1_recall"] is not None
            else None
        ),
        "cost_per_successful_ticket_usd": {
            "v1": a["cost_per_successful_ticket_usd"],
            "v2": b["cost_per_successful_ticket_usd"],
        },
    }


def disagreements(v1: Dict[str, Any], v2: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_id = {record["ticket_id"]: record for record in v1["records"]}
    diffs: List[Dict[str, Any]] = []

    for right in v2["records"]:
        left = by_id.get(right["ticket_id"])
        if left is None or left["prediction"] is None or right["prediction"] is None:
            continue
        if (
            left["prediction"]["severity"] == right["prediction"]["severity"]
            and left["prediction"]["category"] == right["prediction"]["category"]
        ):
            continue

        diffs.append(
            {
                "ticket_id": right["ticket_id"],
                "ground_truth": right["ground_truth"],
                "v1": left["prediction"],
                "v2": right["prediction"],
                "v1_correct": left["correct"],
                "v2_correct": right["correct"],
                "regression": bool(left["correct"] and not right["correct"]),
                "improvement": bool(right["correct"] and not left["correct"]),
            }
        )
    return diffs


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def print_summary(report: Dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print(f"ModelShield benchmark  ({report['mode']})  {report['generated_at']}")
    print("=" * 78)
    header = f"{'metric':<34}{'v1':>18}{'v2':>18}"
    print(header)
    print("-" * 78)

    v1 = report["stacks"].get("v1")
    v2 = report["stacks"].get("v2")

    def row(label: str, key: str, digits: int = 2) -> None:
        left = _fmt(v1["metrics"].get(key), digits) if v1 else "-"
        right = _fmt(v2["metrics"].get(key), digits) if v2 else "-"
        print(f"{label:<34}{left:>18}{right:>18}")

    row("Accuracy", "accuracy")
    row("P1 recall", "p1_recall")
    row("Cost / 10K tickets (USD)", "cost_per_10k_tickets_usd", 4)
    row("Cost / successful ticket", "cost_per_successful_ticket_usd", 8)
    row("p95 latency (ms)", "p95_latency_ms", 0)
    row("Frontier tokens", "total_frontier_tokens", 0)
    row("Lambda GB-seconds", "total_lambda_gb_seconds", 4)
    row("Cache hits", "cache_hits", 0)
    row("Escalations", "escalations", 0)
    row("Fallbacks", "fallbacks", 0)
    print("-" * 78)

    delta = report.get("delta")
    if delta:
        print(
            "cost/10K reduction: {c}%   p95 reduction: {p}%   frontier tokens avoided: {f}%   "
            "GB-seconds reduction: {g}%   accuracy delta: {a} pp".format(
                c=_fmt(delta["cost_per_10k_reduction_pct"]),
                p=_fmt(delta["p95_latency_reduction_pct"]),
                f=_fmt(delta["frontier_tokens_avoided_pct"]),
                g=_fmt(delta["lambda_gb_seconds_reduction_pct"]),
                a=_fmt(delta["accuracy_delta_pp"]),
            )
        )
        print(f"Disagreements: {len(report.get('disagreements', []))}")

    print(f"Report: {report['output_path']}\n")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
async def amain(args: argparse.Namespace) -> int:
    dataset = load_dataset(Path(args.dataset))
    tickets = dataset["tickets"]
    if args.limit:
        tickets = tickets[: args.limit]

    dist = distribution(tickets)
    if args.validate_only:
        print(json.dumps(dist, indent=2))
        print(f"Dataset OK: {args.dataset}")
        return 0

    stacks: List[Tuple[str, str]] = []
    if args.v1_url:
        stacks.append(("v1", args.v1_url))
    if args.v2_url:
        stacks.append(("v2", args.v2_url))
    if not stacks:
        print("error: provide --v1-url and/or --v2-url (or use --validate-only)", file=sys.stderr)
        return 2

    results: Dict[str, Any] = {}
    for name, url in stacks:
        print(f"\nRunning {name} stack: {url}  ({len(tickets)} tickets, concurrency={args.concurrency})")
        results[name] = await run_stack(
            name=name,
            base_url=url,
            tickets=tickets,
            concurrency=args.concurrency,
            timeout=args.timeout,
            attempts=args.attempts,
            pacing=args.pacing,
        )

    report: Dict[str, Any] = {
        "mode": "live",
        "generated_at": utc_now(),
        "dataset": {
            "path": str(Path(args.dataset)),
            "tickets_used": len(tickets),
            **dist,
        },
        "concurrency": args.concurrency,
        "pacing_seconds": args.pacing,
        "stacks": results,
    }

    if "v1" in results and "v2" in results:
        report["delta"] = compare(results["v1"], results["v2"])
        report["disagreements"] = disagreements(results["v1"], results["v2"])
        report["regressions"] = [
            diff for diff in report["disagreements"] if diff["regression"]
        ]

    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report["output_path"] = str(output_path)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print_summary(report)
    return 0 if all(result["metrics"]["successful_requests"] for result in results.values()) else 1


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ModelShield 100-ticket benchmark")
    parser.add_argument("--v1-url", help="Base URL of the modelshield-v1 API")
    parser.add_argument("--v2-url", help="Base URL of the modelshield-v2 API")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="Dataset JSON path")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Report output path")
    parser.add_argument("--concurrency", type=int, default=2, help="In-flight requests per stack (default 2)")
    parser.add_argument("--pacing", type=float, default=2.0, help="Seconds between request starts (~30/min)")
    parser.add_argument("--timeout", type=float, default=60.0, help="Per-request timeout seconds")
    parser.add_argument("--attempts", type=int, default=2, help="Attempts per ticket on 5xx/transport errors")
    parser.add_argument("--limit", type=int, default=0, help="Only replay the first N tickets")
    parser.add_argument("--validate-only", action="store_true", help="Validate the dataset and exit")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.concurrency < 1:
        print("error: --concurrency must be >= 1", file=sys.stderr)
        return 2
    if args.concurrency > 2:
        print(f"warning: clamping --concurrency from {args.concurrency} to 2 (Bedrock quota)", file=sys.stderr)
        args.concurrency = 2
    if args.pacing < 1.5:
        print(f"warning: clamping --pacing from {args.pacing} to 1.5s (Bedrock quota)", file=sys.stderr)
        args.pacing = 1.5
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 130
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
