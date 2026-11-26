"""CloudWatch Embedded Metric Format (EMF) emitter.

One compact JSON object is printed to stdout per triage request. CloudWatch
Logs extracts the metrics under the ``ModelShield/Triage`` namespace without
any PutMetricData API call, so observability adds zero extra API cost or
latency to the request path.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

NAMESPACE = "ModelShield/Triage"

_METRICS = (
    ("EstimatedCostUSD", "None"),
    ("LatencyMs", "Milliseconds"),
    ("LambdaGBSeconds", "None"),
    ("FrontierTokens", "Count"),
    ("CacheHit", "Count"),
    ("Escalated", "Count"),
    ("FallbackTriggered", "Count"),
)


def emit_triage_metrics(
    *,
    stack_version: str,
    model_id: str,
    route_decision: str,
    estimated_cost_usd: float,
    latency_ms: int,
    lambda_gb_seconds: float,
    frontier_tokens: int,
    cache_hit: bool = False,
    escalated: bool = False,
    fallback_triggered: bool = False,
) -> Dict[str, Any]:
    """Print a single valid EMF document and return it (useful for tests)."""

    payload: Dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [["StackVersion"]],
                    "Metrics": [{"Name": name, "Unit": unit} for name, unit in _METRICS],
                }
            ],
        },
        "StackVersion": stack_version,
        "ModelId": model_id,
        "RouteDecision": route_decision,
        "EstimatedCostUSD": round(float(estimated_cost_usd), 10),
        "LatencyMs": int(latency_ms),
        "LambdaGBSeconds": round(float(lambda_gb_seconds), 6),
        "FrontierTokens": int(frontier_tokens),
        "CacheHit": 1 if cache_hit else 0,
        "Escalated": 1 if escalated else 0,
        "FallbackTriggered": 1 if fallback_triggered else 0,
    }

    # EMF is parsed line-by-line from stdout: never pretty-print this payload.
    print(json.dumps(payload, separators=(",", ":")), flush=True)
    return payload
