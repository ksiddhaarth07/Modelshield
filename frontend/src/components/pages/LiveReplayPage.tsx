import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Terminal } from "lucide-react";
import { usd } from "../../lib/format";
import type { RouteDecision, TriageResult } from "../../lib/types";

interface LiveReplayPageProps {
  v1: TriageResult[];
  v2: TriageResult[];
  running: boolean;
  progress: number;
  total: number;
}

function TypewriterLine({ text }: { text: string }) {
  const [shown, setShown] = useState("");

  useEffect(() => {
    setShown("");
    let i = 0;
    const id = window.setInterval(() => {
      i += 1;
      setShown(text.slice(0, i));
      if (i >= text.length) window.clearInterval(id);
    }, 18);
    return () => window.clearInterval(id);
  }, [text]);

  return (
    <span className="font-mono text-[11px] text-neon-cyan">
      {shown}
      <span className="animate-pulse">_</span>
    </span>
  );
}

function routeBadge(route: RouteDecision) {
  switch (route) {
    case "cache_hit":
      return {
        label: "CACHE HIT",
        cls: "border-neon-purple/40 bg-neon-purple/15 text-neon-purple",
      };
    case "nova_lite":
      return {
        label: "NOVA LITE",
        cls: "border-neon-cyan/40 bg-neon-cyan/15 text-neon-cyan shadow-[0_0_12px_rgba(0,194,255,0.2)]",
      };
    case "escalated_pro":
      return {
        label: "ESCALATED PRO",
        cls: "border-neon-orange/40 bg-neon-orange/15 text-neon-orange",
      };
    case "direct_pro":
      return {
        label: "DIRECT PRO",
        cls: "border-rose-400/40 bg-rose-500/15 text-rose-300",
      };
    case "fallback_pro":
      return {
        label: "FALLBACK PRO",
        cls: "border-amber-400/40 bg-amber-500/15 text-amber-300",
      };
    default:
      return {
        label: "SINGLE HEAVY",
        cls: "border-white/10 bg-white/5 text-slate-400",
      };
  }
}

export default function LiveReplayPage({
  v1,
  v2,
  running,
  progress,
  total,
}: LiveReplayPageProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [mobileTab, setMobileTab] = useState<"v1" | "v2">("v2");

  const latestV2 = v2[v2.length - 1];
  const terminalText =
    running && latestV2
      ? `[BEDROCK] ${latestV2.ticket_id} -> ${latestV2.telemetry.route_decision.toUpperCase()} (${latestV2.severity} ${latestV2.category}) · ${Math.round(latestV2.telemetry.latency_ms)}ms · ${usd(latestV2.telemetry.estimated_cost_usd, 6)}`
      : v2.length > 0
        ? `[COMPLETE] ${v2.length} tickets replayed across v1 (Nova Pro) & v2 (Adaptive Router). Tap or hover any row for breakdown.`
        : `[READY] Awaiting 100-ticket live replay stream against ap-southeast-2 endpoints.`;

  const v1Ordered = [...v1].reverse();
  const v2Ordered = [...v2].reverse();

  const renderV1Card = (extraClass = "") => (
    <div className={`card flex min-h-0 flex-col overflow-hidden p-4 ${extraClass}`}>
      <div className="mb-3 flex items-center justify-between border-b border-white/[0.06] pb-3">
        <div>
          <p className="font-display text-xs font-bold text-slate-200">v1-before · Single Heavy</p>
          <p className="text-[11px] font-medium text-slate-400">100% Nova Pro · x86_64 · 512 MB</p>
        </div>
        <span className="rounded-full bg-white/[0.06] px-2.5 py-0.5 text-[11px] font-semibold text-slate-300 tnum">
          {v1.length}
        </span>
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {v1Ordered.length === 0 ? (
          <p className="py-12 text-center text-xs text-slate-400">
            Tap Start Live Replay to stream v1 baseline responses.
          </p>
        ) : (
          v1Ordered.map((r) => (
            <motion.div
              key={`v1-${r.ticket_id}`}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="card2 flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 text-xs sm:flex-nowrap"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 font-mono text-[10px] font-bold text-slate-300">
                  {r.severity}
                </span>
                <span className="font-mono text-[11px] text-slate-400">
                  #{r.ticket_id.replace("tkt-", "")}
                </span>
                <span className="truncate text-slate-300">{r.category}</span>
              </div>
              <div className="flex shrink-0 items-center gap-3 font-mono text-[11px] tnum">
                <span className="text-slate-400">{Math.round(r.telemetry.latency_ms)}ms</span>
                <span className="text-slate-200">{usd(r.telemetry.estimated_cost_usd, 6)}</span>
              </div>
            </motion.div>
          ))
        )}
      </div>
    </div>
  );

  const renderV2Card = (extraClass = "") => (
    <div
      className={`card flex min-h-0 flex-col overflow-hidden p-4 ${extraClass}`}
      style={{ borderColor: "rgba(0,194,255,0.22)" }}
    >
      <div className="mb-3 flex items-center justify-between border-b border-white/[0.06] pb-3">
        <div>
          <p className="font-display text-xs font-bold text-neon-cyan">v2-after · Adaptive Router</p>
          <p className="text-[11px] font-medium text-slate-400">
            TTL Cache → Nova Lite → Targeted Pro · arm64
          </p>
        </div>
        <span className="rounded-full bg-neon-cyan/15 px-2.5 py-0.5 text-[11px] font-semibold text-neon-cyan tnum">
          {v2.length}
        </span>
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
        {v2Ordered.length === 0 ? (
          <p className="py-12 text-center text-xs text-slate-400">
            Tap Start Live Replay to stream v2 adaptive router responses.
          </p>
        ) : (
          v2Ordered.map((r) => {
            const badge = routeBadge(r.telemetry.route_decision);
            const isExpanded = expandedId === r.ticket_id;
            const matchingV1 = v1.find((x) => x.ticket_id === r.ticket_id);
            const tokensSaved = matchingV1
              ? Math.max(0, matchingV1.telemetry.frontier_tokens_used - r.telemetry.frontier_tokens_used)
              : Math.max(0, 400 - r.telemetry.frontier_tokens_used);

            return (
              <motion.div
                key={`v2-${r.ticket_id}`}
                layout
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                whileTap={{ scale: 0.98 }}
                onClick={() => setExpandedId(isExpanded ? null : r.ticket_id)}
                onMouseEnter={() => setExpandedId(r.ticket_id)}
                onMouseLeave={() => setExpandedId(null)}
                data-hover="1"
                className="card2 cursor-pointer overflow-hidden px-3.5 py-2.5 text-xs transition-colors hover:border-neon-cyan/30"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 sm:flex-nowrap">
                  <div className="flex min-w-0 items-center gap-2.5">
                    <span className="rounded-md bg-neon-cyan/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-neon-cyan">
                      {r.severity}
                    </span>
                    <span className="font-mono text-[11px] text-slate-400">
                      #{r.ticket_id.replace("tkt-", "")}
                    </span>
                    <span className="truncate text-slate-200">{r.category}</span>
                  </div>

                  {/* Mobile: time/cost sit cleanly on top right, badge wraps gracefully underneath */}
                  <div className="flex w-full flex-row-reverse items-center justify-between gap-2 sm:w-auto sm:flex-row sm:justify-end">
                    <span
                      className={`rounded-full border px-2 py-0.5 text-[9px] font-bold tracking-wide ${badge.cls}`}
                    >
                      {badge.label}
                    </span>
                    <div className="flex items-center gap-2.5 font-mono text-[11px] tnum">
                      <span className="text-slate-400">{Math.round(r.telemetry.latency_ms)}ms</span>
                      <span className="font-semibold text-neon-green">
                        {usd(r.telemetry.estimated_cost_usd, 6)}
                      </span>
                    </div>
                  </div>
                </div>

                <AnimatePresence>
                  {isExpanded && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      className="mt-2.5 border-t border-white/[0.06] pt-2 text-[11px] text-slate-400"
                    >
                      <p className="line-clamp-2 text-slate-300">
                        <span className="text-slate-500">Summary:</span> {r.summary}
                      </p>
                      <div className="mt-1.5 flex flex-wrap gap-3 font-mono text-[10px]">
                        <span>
                          Model: <strong className="text-neon-cyan">{r.telemetry.model_id}</strong>
                        </span>
                        <span>
                          Conf: <strong className="text-white">{(r.confidence * 100).toFixed(0)}%</strong>
                        </span>
                        <span>
                          Saved: <strong className="text-neon-green">{tokensSaved} tok</strong>
                        </span>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })
        )}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col gap-3.5 md:h-full md:overflow-hidden">
      {/* Header + Typewriter Terminal Strip */}
      <div className="card flex flex-wrap items-center justify-between gap-3 px-4 py-3 md:px-5 md:py-3.5">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-semibold text-white tnum">
            <span
              className={`h-2 w-2 rounded-full ${
                running ? "bg-neon-green pulse-dot" : "bg-neon-cyan"
              }`}
            />
            {running
              ? `Replaying ${progress}/${total}`
              : `${Math.max(v1.length, v2.length)}/${total} Tickets`}
          </div>
          <div className="hidden items-center gap-2 rounded-xl border border-white/[0.06] bg-black/30 px-3 py-1.5 md:flex">
            <Terminal size={12} className="text-neon-cyan" />
            <TypewriterLine text={terminalText} />
          </div>
        </div>
      </div>

      {/* Mobile Segmented Toggle (< lg) */}
      <div className="flex rounded-2xl border border-white/10 bg-white/[0.03] p-1 lg:hidden">
        {(
          [
            { id: "v1", label: `v1 BEFORE (${v1.length})` },
            { id: "v2", label: `v2 AFTER (${v2.length})` },
          ] as const
        ).map((tab) => {
          const active = mobileTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setMobileTab(tab.id)}
              className={`relative flex min-h-[44px] flex-1 items-center justify-center rounded-xl text-xs font-semibold transition-colors ${
                active ? "text-white" : "text-slate-400"
              }`}
            >
              {active && (
                <motion.div
                  layoutId="replay-mobile-pill"
                  className="absolute inset-0 rounded-xl border border-cyan-400/35 bg-gradient-to-r from-purple-500/25 to-cyan-500/25"
                />
              )}
              <span className="relative z-10 tnum">{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Mobile Full-Width Stream (< lg) */}
      <div className="lg:hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={mobileTab}
            initial={{ opacity: 0, x: mobileTab === "v2" ? 16 : -16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: mobileTab === "v2" ? -16 : 16 }}
            transition={{ duration: 0.18 }}
          >
            {mobileTab === "v1" ? renderV1Card("max-h-[62vh]") : renderV2Card("max-h-[62vh]")}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Desktop Split-Screen Stream (lg+) — strictly untouched */}
      <div className="hidden min-h-0 flex-1 gap-4 lg:grid lg:grid-cols-2">
        {renderV1Card()}
        {renderV2Card()}
      </div>
    </div>
  );
}
