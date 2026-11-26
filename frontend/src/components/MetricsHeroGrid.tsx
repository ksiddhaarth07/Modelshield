import type { ReactNode } from "react";
import { ms, percent, usd, usdPer10k } from "../lib/format";
import { reductionPct } from "../lib/metrics";
import type { RunMetrics } from "../lib/types";

interface MetricsHeroGridProps {
  v1: RunMetrics | null;
  v2: RunMetrics | null;
  running: boolean;
}

function MetricCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="glass flex flex-col justify-between gap-2 p-4">
      <p className="kicker">{label}</p>
      {children}
    </section>
  );
}

function DeltaBadge({ value }: { value: number | null }) {
  if (value === null) return <span className="text-[11px] text-slate-400">vs v1</span>;
  const good = value >= 0;
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold tnum ${
        good
          ? "border-emerald-200 bg-emerald-50 text-emerald-700"
          : "border-rose-200 bg-rose-50 text-rose-700"
      }`}
    >
      {good ? "−" : "+"}
      {Math.abs(value).toFixed(1)}%
    </span>
  );
}

function Pair({
  v1,
  v2,
  render,
}: {
  v1: RunMetrics | null;
  v2: RunMetrics | null;
  render: (metrics: RunMetrics | null) => string;
}) {
  return (
    <div className="flex items-end gap-2">
      <span className="text-[11px] font-medium text-slate-400">v1</span>
      <span className="text-lg font-semibold tracking-tight text-slate-900 tnum">{render(v1)}</span>
      <span className="pb-0.5 text-slate-300">→</span>
      <span className="text-[11px] font-medium text-slate-400">v2</span>
      <span className="text-2xl font-semibold tracking-tight text-slate-900 tnum">{render(v2)}</span>
    </div>
  );
}

export default function MetricsHeroGrid({ v1, v2, running }: MetricsHeroGridProps) {
  const costDelta = v1 && v2 ? reductionPct(v1.costPer10kUsd, v2.costPer10kUsd) : null;
  const latencyDelta = v1 && v2 ? reductionPct(v1.p95LatencyMs, v2.p95LatencyMs) : null;
  const tokenDelta = v1 && v2 ? reductionPct(v1.frontierTokens, v2.frontierTokens) : null;
  const gbDelta = v1 && v2 ? reductionPct(v1.gbSeconds, v2.gbSeconds) : null;

  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <MetricCard label="Cost per 10K tickets">
        <div className="flex items-end justify-between gap-2">
          <Pair v1={v1} v2={v2} render={(m) => (m ? usdPer10k(m.costPer10kUsd) : "—")} />
          <DeltaBadge value={costDelta} />
        </div>
        <p className="text-[11px] text-slate-500">
          {v1 && v2
            ? `${usd(v1.totalCostUsd)} → ${usd(v2.totalCostUsd)} across ${v2.attempted} tickets`
            : running
              ? "Measuring live Bedrock spend…"
              : "Run the replay to measure exact token spend"}
        </p>
      </MetricCard>

      <MetricCard label="p95 latency">
        <div className="flex items-end justify-between gap-2">
          <Pair v1={v1} v2={v2} render={(m) => (m ? ms(m.p95LatencyMs) : "—")} />
          <DeltaBadge value={latencyDelta} />
        </div>
        <p className="text-[11px] text-slate-500">
          End-to-end handler time, measured per request (not modelled)
        </p>
      </MetricCard>

      <MetricCard label="Accuracy & P1 recall">
        <div className="flex items-end justify-between gap-2">
          <span className="text-2xl font-semibold tracking-tight tnum">
            {v2 ? percent(v2.accuracy * 100, 0) : "—"}
          </span>
          {v2?.p1Recall !== null && v2?.p1Recall !== undefined ? (
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
                v2.p1Recall >= 1
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : "border-amber-200 bg-amber-50 text-amber-700"
              }`}
            >
              {percent(v2.p1Recall * 100, 0)} P1 recall
            </span>
          ) : (
            <span className="text-[10px] text-slate-400">P1 recall</span>
          )}
        </div>
        <p className="text-[11px] text-slate-500">
          {v2
            ? `Cost / successful ticket ${usd(v2.costPerSuccessfulUsd, 8)} · v1 ${usd(v1?.costPerSuccessfulUsd, 8)}`
            : "Severity + category exact match on 100 labelled tickets"}
        </p>
      </MetricCard>

      <MetricCard label="Compute footprint">
        <div className="flex items-end justify-between gap-2">
          <span className="text-2xl font-semibold tracking-tight tnum">
            {tokenDelta !== null ? `${tokenDelta.toFixed(0)}%` : "—"}
          </span>
          <span className="pb-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
            frontier tokens avoided
          </span>
        </div>
        <p className="text-[11px] text-slate-500">
          {gbDelta !== null
            ? `${gbDelta.toFixed(1)}% fewer Lambda GB-seconds · ${v2?.cacheHits ?? 0} cache hits · ${v2?.escalations ?? 0} escalations`
            : "Nova Pro tokens avoided and Lambda GB-seconds reduced"}
        </p>
      </MetricCard>
    </div>
  );
}
