import type { HealthState } from "../lib/types";

interface HeaderBarProps {
  v1Health: HealthState;
  v2Health: HealthState;
  running: boolean;
  progress: number;
  total: number;
  canRun: boolean;
  onRun: () => void;
  onOpenCustom: () => void;
}

const STATE_LABEL: Record<HealthState, string> = {
  ok: "live",
  down: "unreachable",
  unknown: "checking",
  unconfigured: "not configured",
};

const DOT_CLASS: Record<HealthState, string> = {
  ok: "bg-emerald-500",
  down: "bg-rose-500",
  unknown: "bg-amber-400 animate-pulse",
  unconfigured: "bg-slate-300",
};

function StatusPill({ label, state }: { label: string; state: HealthState }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white/70 px-3 py-1 text-[11px]">
      <span className={`h-1.5 w-1.5 rounded-full ${DOT_CLASS[state]}`} />
      <span className="font-medium text-slate-700">{label}</span>
      <span className="text-slate-400">{STATE_LABEL[state]}</span>
    </span>
  );
}

export default function HeaderBar({
  v1Health,
  v2Health,
  running,
  progress,
  total,
  canRun,
  onRun,
  onOpenCustom,
}: HeaderBarProps) {
  return (
    <header className="glass flex flex-wrap items-center justify-between gap-3 px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-xl bg-slate-900 text-[11px] font-bold tracking-tight text-white">
          MS
        </div>
        <div>
          <h1 className="text-[15px] font-semibold leading-4 tracking-tight">ModelShield</h1>
          <p className="mt-0.5 text-[11px] text-slate-500">
            Live triage benchmark · API Gateway → Lambda → Bedrock → DynamoDB → CloudWatch
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <StatusPill label="v1 · Nova Pro" state={v1Health} />
        <StatusPill label="v2 · Router" state={v2Health} />
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onOpenCustom}
          className="rounded-xl border border-slate-200 bg-white/70 px-3 py-2 text-[12px] font-medium text-slate-700 transition hover:bg-white disabled:opacity-40"
          disabled={running}
        >
          Test single ticket
        </button>
        <button
          type="button"
          onClick={onRun}
          disabled={!canRun || running}
          className="inline-flex items-center gap-2 rounded-xl bg-slate-900 px-4 py-2 text-[12px] font-semibold text-white shadow-sm transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          <svg width="11" height="11" viewBox="0 0 12 12" fill="none" aria-hidden="true">
            <path d="M2.5 1.6v8.8L10 6 2.5 1.6Z" fill="currentColor" />
          </svg>
          {running ? `Replaying ${progress}/${total}` : "Run 100-ticket live replay"}
        </button>
      </div>
    </header>
  );
}
