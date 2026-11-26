export type Severity = "P1" | "P2" | "P3" | "P4";
export type Category =
  | "incident"
  | "security"
  | "billing"
  | "account"
  | "how_to"
  | "bug";

export type RouteDecision =
  | "single_heavy"
  | "cache_hit"
  | "nova_lite"
  | "escalated_pro"
  | "direct_pro"
  | "fallback_pro";

export interface Telemetry {
  stack_version: string;
  route_decision: RouteDecision;
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
}

export interface TriageResult {
  ticket_id: string;
  severity: Severity;
  category: Category;
  confidence: number;
  summary: string;
  draft_reply: string;
  telemetry: Telemetry;
}

export interface Ticket {
  ticket_id: string;
  subject: string;
  body: string;
  ground_truth: {
    severity: Severity;
    category: Category;
  };
}

export interface Health {
  status: string;
  stack_version?: string;
  model_id?: string;
  architecture?: string;
}

export type HealthState = "ok" | "down" | "unknown" | "unconfigured";

export interface RunMetrics {
  attempted: number;
  completed: number;
  failed: number;
  correct: number;
  accuracy: number;
  p1Recall: number | null;
  p95LatencyMs: number;
  totalCostUsd: number;
  costPer10kUsd: number;
  costPerSuccessfulUsd: number | null;
  gbSeconds: number;
  frontierTokens: number;
  cacheHits: number;
  escalations: number;
  fallbacks: number;
}

export interface ReplayOutcome {
  results: TriageResult[];
  failures: number;
}
