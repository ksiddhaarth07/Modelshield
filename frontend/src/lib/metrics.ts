import type { RunMetrics, Ticket, TriageResult } from "./types";

/** Linear-interpolated percentile; p95 is the default for latency reporting. */
export function percentile(values: number[], p: number): number {
  if (values.length === 0) return 0;
  const ordered = [...values].sort((a, b) => a - b);
  if (ordered.length === 1) return ordered[0];
  const rank = ((ordered.length - 1) * p) / 100;
  const lower = Math.floor(rank);
  const upper = Math.ceil(rank);
  if (lower === upper) return ordered[rank];
  return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower);
}

export function summarize(
  results: TriageResult[],
  truth: Map<string, Ticket>,
  failures = 0,
): RunMetrics {
  const completed = results.length;
  const attempted = completed + failures;

  let correct = 0;
  let p1Total = 0;
  let p1Hit = 0;

  for (const result of results) {
    const expected = truth.get(result.ticket_id)?.ground_truth;
    if (!expected) continue;
    if (expected.severity === result.severity && expected.category === result.category) {
      correct += 1;
    }
    if (expected.severity === "P1") {
      p1Total += 1;
      if (result.severity === "P1") p1Hit += 1;
    }
  }

  const latencies = results.map((result) => Number(result.telemetry?.latency_ms ?? 0));
  const totalCostUsd = results.reduce(
    (sum, result) => sum + Number(result.telemetry?.estimated_cost_usd ?? 0),
    0,
  );
  const gbSeconds = results.reduce(
    (sum, result) => sum + Number(result.telemetry?.lambda_gb_seconds ?? 0),
    0,
  );
  const frontierTokens = results.reduce(
    (sum, result) => sum + Number(result.telemetry?.frontier_tokens_used ?? 0),
    0,
  );

  return {
    attempted,
    completed,
    failed: failures,
    correct,
    accuracy: attempted > 0 ? correct / attempted : 0,
    p1Recall: p1Total > 0 ? p1Hit / p1Total : null,
    p95LatencyMs: percentile(latencies, 95),
    totalCostUsd,
    costPer10kUsd: attempted > 0 ? (totalCostUsd / attempted) * 10_000 : 0,
    costPerSuccessfulUsd: correct > 0 ? totalCostUsd / correct : null,
    gbSeconds,
    frontierTokens,
    cacheHits: results.filter((result) => result.telemetry?.cache_hit).length,
    escalations: results.filter((result) => result.telemetry?.escalated).length,
    fallbacks: results.filter((result) => result.telemetry?.fallback_triggered).length,
  };
}

export function reductionPct(before: number | null, after: number | null): number | null {
  if (before === null || after === null || before === 0) return null;
  return (1 - after / before) * 100;
}
