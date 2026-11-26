import { useEffect, useState } from "react";
import { usd } from "../lib/format";
import type { TriageResult } from "../lib/types";

interface CustomTicketDrawerProps {
  open: boolean;
  loading: boolean;
  results: { v1: TriageResult | string | null; v2: TriageResult | string | null };
  onClose: () => void;
  onSubmit: (subject: string, body: string) => void;
}

const SAMPLE_SUBJECT = "Checkout webhooks timing out after regional failover";
const SAMPLE_BODY =
  "Multiple enterprise tenants report 503 errors on payment confirmation webhooks since 04:12 UTC. The failures started after the regional failover and are still ongoing.";

function ResultPanel({ label, result }: { label: string; result: TriageResult | string | null }) {
  if (result === null) {
    return (
      <div className="rounded-xl border border-dashed border-slate-200 p-3">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
        <p className="mt-2 text-[11px] text-slate-400">No response yet</p>
      </div>
    );
  }

  if (typeof result === "string") {
    return (
      <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-rose-500">{label}</p>
        <p className="mt-1 break-words text-[11px] text-rose-700">{result}</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white/70 p-3">
      <div className="flex items-center justify-between">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{label}</p>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[9px] font-semibold text-slate-600">
          {result.telemetry?.route_decision}
        </span>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-lg font-semibold tracking-tight">{result.severity}</span>
        <span className="text-[11px] text-slate-500">{result.category.replace("_", " ")}</span>
        <span className="ml-auto text-[10px] text-slate-400 tnum">
          {Math.round(result.telemetry?.latency_ms ?? 0)}ms · {usd(result.telemetry?.estimated_cost_usd, 6)}
        </span>
      </div>
      <p className="mt-1 line-clamp-2 text-[11px] text-slate-600">{result.summary}</p>
    </div>
  );
}

export default function CustomTicketDrawer({
  open,
  loading,
  results,
  onClose,
  onSubmit,
}: CustomTicketDrawerProps) {
  const [subject, setSubject] = useState(SAMPLE_SUBJECT);
  const [body, setBody] = useState(SAMPLE_BODY);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const valid = subject.trim().length >= 3 && body.trim().length >= 10;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/25 p-4 backdrop-blur-sm"
      onMouseDown={onClose}
    >
      <div
        className="glass w-full max-w-3xl p-5"
        onMouseDown={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Test a single custom ticket"
      >
        <div className="flex items-start justify-between">
          <div>
            <p className="kicker">Single ticket tester</p>
            <h2 className="mt-1 text-base font-semibold tracking-tight">Send one ticket to both stacks</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-500 hover:bg-slate-50"
          >
            Close
          </button>
        </div>

        <div className="mt-4 grid gap-3">
          <label className="grid gap-1">
            <span className="text-[11px] font-medium text-slate-600">Subject</span>
            <input
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              className="rounded-xl border border-slate-200 bg-white/80 px-3 py-2 text-[12px] outline-none focus:border-slate-400"
            />
          </label>
          <label className="grid gap-1">
            <span className="text-[11px] font-medium text-slate-600">Body</span>
            <textarea
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={4}
              className="resize-none rounded-xl border border-slate-200 bg-white/80 px-3 py-2 text-[12px] outline-none focus:border-slate-400"
            />
          </label>
        </div>

        <div className="mt-3 flex items-center justify-between">
          <p className="text-[10px] text-slate-400">
            Same API contract as the benchmark · no ticket is written unless the stack persists it.
          </p>
          <button
            type="button"
            disabled={!valid || loading}
            onClick={() => onSubmit(subject.trim(), body.trim())}
            className="rounded-xl bg-slate-900 px-4 py-2 text-[12px] font-semibold text-white transition hover:bg-slate-800 disabled:opacity-40"
          >
            {loading ? "Triaging…" : "Triage on both stacks"}
          </button>
        </div>

        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <ResultPanel label="v1 · single heavy" result={results.v1} />
          <ResultPanel label="v2 · adaptive router" result={results.v2} />
        </div>
      </div>
    </div>
  );
}
