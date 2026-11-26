import report from "../../../eval/results/benchmark_report.json";
import type { Category, RouteDecision, Severity, TriageResult } from "../lib/types";

interface RawRecord {
  ticket_id: string;
  prediction?: {
    severity?: string;
    category?: string;
    confidence?: number;
  };
  telemetry: {
    stack_version: string;
    route_decision: string;
    model_id: string;
    cache_hit: boolean;
    escalated: boolean;
    fallback_triggered: boolean;
    input_tokens: number;
    output_tokens: number;
    frontier_tokens_used: number;
    estimated_cost_usd: number;
    latency_ms: number;
    lambda_memory_mb: number;
    lambda_gb_seconds: number;
    architecture: string;
  };
}

function mapRecords(records: RawRecord[]): TriageResult[] {
  return records
    .filter((r) => r.prediction && r.telemetry)
    .map((r) => ({
      ticket_id: r.ticket_id,
      severity: (r.prediction?.severity ?? "P3") as Severity,
      category: (r.prediction?.category ?? "how_to") as Category,
      confidence: Number(r.prediction?.confidence ?? 0),
      summary: "",
      draft_reply: "",
      telemetry: {
        ...r.telemetry,
        route_decision: r.telemetry.route_decision as RouteDecision,
      },
    }));
}

export const INITIAL_V1_RESULTS: TriageResult[] = mapRecords(
  (report.stacks?.v1?.records ?? []) as RawRecord[],
);

export const INITIAL_V2_RESULTS: TriageResult[] = mapRecords(
  (report.stacks?.v2?.records ?? []) as RawRecord[],
);
