import { usd } from "../lib/format";
import type { RouteDecision, Severity, TriageResult } from "../lib/types";

interface LiveTickerSplitProps {
  v1: TriageResult[];
  v2: TriageResult[];
  running: boolean;
  progress: number;
  total: number;
}

const SEVERITY_CLASS: Record<Severity, string> = {
  P1: "border-rose-200 bg-rose-50 text-rose-700",
  P2: "border-amber-200 bg-amber-50 text-amber-700",
  P3: "border-sky-200 bg-sky-50 text-sky-700",
  P4: "border-slate-200 bg-slate-50 text-slate-600",
};

const ROUTE: Record<RouteDecision, { label: string; className: string }> = {
  single_heavy: { label: "NOVA PRO", className: "border-indigo-200 bg-indigo-50 text-indigo-700" },
  cache_hit: { label: "CACHE HIT", className: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  nova_lite: { label: "NOVA LITE", className: "border-sky-200 bg-sky-50 text-sky-700" },
  escalated_pro: { label: "ESCALATED → PRO", className: "border-amber-200 bg-amber-50 text-amber-700" },
  direct_pro: { label: "DIRECT PRO", className: "border-indigo-200 bg-indigo-50 text-indigo-700" },
  fallback_pro: { label: "FALLBACK → PRO", className: "border-rose-200 bg-rose-50 text-rose-700" },
};

function StreamRow({ result, showRoute }: { result: TriageResult; showRoute: boolean }) {
  const route = ROUTE[result.telemetry?.route_decision ?? "single_heavy"] ?? ROUTE.single_heavy;
  return (
    <div className="animate-fade-in flex items-center gap-2 border-b border-slate-100 px-3 py-[7px] text-[11px] last:border-b-0">
      <span
        className={`w-7 shrink-0 rounded-md border px-1 py-0.5 text-center text-[9px] font-bold ${SEVERITY_CLASS[result.severity]}`}
      >
        {result.severity}
      </span>
      <span className="w-14 shrink-0 font-medium text-slate-500 tnum">{result.ticket_id.replace("tkt-", "#")}</span>
      <span className="min-w-0 flex-1 truncate text-slate-600">{result.category.replace("_", " ")}</span>
      {showRoute ? (
        <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold ${route.className}`}>
          {route.label}
        </span>
      ) : null}
      <span className="w-12 shrink-0 text-right text-slate-400 tnum">
        {Math.round(result.telemetry?.latency_ms ?? 0)}ms
      </span>
      <span className="w-[74px] shrink-0 text-right text-slate-400 tnum">
        {usd(result.telemetry?.estimated_cost_usd, 6)}
      </span>
    </div>
  );
}

function StreamColumn({
  title,
  subtitle,
  results,
  showRoute,
  running,
}: {
  title: string;
  subtitle: string;
  results: TriageResult[];
  showRoute: boolean;
  running: boolean;
}) {
  const ordered = [...results].reverse();
  return (
    <section className="glass flex min-h-0 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-slate-200/70 px-3 py-2">
        <div>
          <p className="text-[12px] font-semibold tracking-tight">{title}</p>
          <p className="text-[10px] text-slate-500">{subtitle}</p>
        </div>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 tnum">
          {results.length}
        </span>
      </div>

      <div className="scroll-thin min-h-0 flex-1 overflow-y-auto">
        {ordered.length === 0 ? (
          <div className="flex h-full min-h-[120px] flex-col items-center justify-center gap-1 text-center">
            <span className={`h-1.5 w-1.5 rounded-full ${running ? "animate-pulse bg-sky-500" : "bg-slate-300"}`} />
            <p className="text-[11px] text-slate-400">
              {running ? "Streaming triage results…" : "Awaiting replay"}
            </p>
          </div>
        ) : (
          ordered.map((result) => (
            <StreamRow key={result.ticket_id} result={result} showRoute={showRoute} />
          ))
        )}
      </div>
    </section>
  );
}

export default function LiveTickerSplit({ v1, v2, running, progress, total }: LiveTickerSplitProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-2">
      <div className="flex items-center justify-between px-1">
        <p className="kicker">Live split replay</p>
        <p className="text-[10px] text-slate-500 tnum">
          {running ? `${progress}/${total} in flight cap 2` : "concurrency capped at 2 per stack"}
        </p>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-2">
        <StreamColumn
          title="v1-before · single heavy"
          subtitle="100% Nova Pro · x86_64 · 512 MB"
          results={v1}
          showRoute={false}
          running={running}
        />
        <StreamColumn
          title="v2-after · adaptive router"
          subtitle="cache → Nova Lite → targeted Pro escalation"
          results={v2}
          showRoute
          running={running}
        />
      </div>
    </div>
  );
}
