import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  Cloud,
  Cpu,
  Database,
  Globe,
  ShieldCheck,
} from "lucide-react";
import { WAR_FINDINGS } from "../../data/war";

const PIPELINE_NODES = [
  {
    id: "apigw",
    title: "API Gateway",
    sub: "25 req/s · burst 50",
    latency: "12 ms",
    saving: "Spend cap (COST08-BP02)",
    icon: Globe,
    color: "#8b5cf6",
    z: 20,
  },
  {
    id: "lambda",
    title: "Lambda Router",
    sub: "arm64 · 256 MB",
    latency: "4 ms",
    saving: "52.2% less GB-s",
    icon: Cpu,
    color: "#06b6d4",
    z: 40,
    active: true,
  },
  {
    id: "dynamo",
    title: "DynamoDB Cache",
    sub: "24h TTL · fail-open",
    latency: "9 ms",
    saving: "$0.00 repeat hits",
    icon: Database,
    color: "#34d399",
    z: 30,
  },
  {
    id: "bedrock",
    title: "Amazon Bedrock",
    sub: "Nova Lite → Pro",
    latency: "510 ms",
    saving: "-80.4% token spend",
    icon: Activity,
    color: "#f472b6",
    z: 45,
  },
  {
    id: "cw",
    title: "CloudWatch EMF",
    sub: "14d retention",
    latency: "Async",
    saving: "Full route telemetry",
    icon: Cloud,
    color: "#fb923c",
    z: 20,
  },
];

function badgeStyle(status: string): string {
  if (status === "Implemented") {
    return "border border-emerald-400/70 bg-emerald-500/20 text-emerald-300 shadow-[0_0_12px_rgba(52,211,153,0.35)]";
  }
  if (status === "Partial") {
    return "border border-amber-400/35 bg-amber-500/10 text-amber-300";
  }
  return "border border-red-500/30 bg-red-500/10 text-red-400";
}

export default function WarAuditPage() {
  const [tilt, setTilt] = useState({ rx: 0, ry: 0 });
  const [activeNode, setActiveNode] = useState<string | null>(null);
  const [openBp, setOpenBp] = useState<string | null>(WAR_FINDINGS[0]?.bp ?? null);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (window.matchMedia("(pointer: coarse)").matches) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width - 0.5;
    const y = (e.clientY - rect.top) / rect.height - 0.5;
    setTilt({ rx: -y * 7, ry: x * 9 });
  };

  return (
    <div className="scroll-thin flex flex-col gap-4 pb-2 md:h-full md:overflow-y-auto md:pr-1.5">
      {/* 3D Pipeline on Desktop / Horizontal Swipeable Carousel on Mobile */}
      <div
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setTilt({ rx: 0, ry: 0 })}
        className="card relative shrink-0 p-4 md:p-6"
        style={{ perspective: "1000px" }}
      >
        <div className="pointer-events-none absolute inset-0 overflow-hidden rounded-[20px]">
          <div
            className="absolute -left-16 -top-16 h-60 w-60 rounded-full opacity-20 blur-3xl"
            style={{ background: "radial-gradient(circle, #8b5cf6, transparent 70%)" }}
          />
          <div
            className="absolute -bottom-16 right-12 h-64 w-64 rounded-full opacity-20 blur-3xl"
            style={{ background: "radial-gradient(circle, #06b6d4, transparent 70%)" }}
          />
        </div>

        <div className="relative z-10 flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="kicker text-cyan-300">Interactive 3D Architecture</p>
            <h2 className="mt-0.5 font-display text-base font-bold text-white">
              Serverless Triage Pipeline · ap-southeast-2
            </h2>
          </div>
          <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/60 bg-emerald-500/20 px-3 py-1 font-display text-xs font-semibold text-emerald-300 shadow-[0_0_16px_rgba(52,211,153,0.35)] tnum">
            <ShieldCheck size={14} className="text-emerald-300" /> {WAR_FINDINGS.length} BPs Flipped
          </span>
        </div>

        <div className="relative">
          <motion.div
            animate={{ rotateX: tilt.rx, rotateY: tilt.ry }}
            transition={{ type: "spring", stiffness: 200, damping: 20 }}
            style={{ transformStyle: "preserve-3d" }}
            className="scroll-thin relative z-10 mt-4 flex snap-x snap-mandatory gap-3 overflow-x-auto pb-2 md:mt-5 md:grid md:grid-cols-5 md:overflow-visible md:pb-0"
          >
            {PIPELINE_NODES.map((node, idx) => {
              const Icon = node.icon;
              const hovered = activeNode === node.id;
              const isActiveNode = Boolean(node.active);

              return (
                <div key={node.id} className="relative flex min-w-[230px] snap-center items-center md:min-w-0">
                  {isActiveNode && (
                    <div className="pointer-events-none absolute -inset-1 rounded-2xl bg-cyan-500/15 blur-xl animate-pulse" />
                  )}

                  <motion.div
                    onMouseEnter={() => setActiveNode(node.id)}
                    onMouseLeave={() => setActiveNode(null)}
                    whileHover={{ y: -5, scale: 1.03 }}
                    whileTap={{ scale: 0.96 }}
                    data-hover="1"
                    style={{
                      transform: `translateZ(${node.z}px)`,
                      borderColor: hovered
                        ? node.color
                        : isActiveNode
                          ? "rgba(6, 182, 212, 0.55)"
                          : undefined,
                      boxShadow: hovered
                        ? `0 14px 34px rgba(0,0,0,0.55), 0 0 26px ${node.color}40`
                        : isActiveNode
                          ? "0 12px 32px rgba(0,0,0,0.5), 0 0 30px rgba(6,182,212,0.3)"
                          : "0 12px 30px rgba(0,0,0,0.45)",
                    }}
                    className="relative flex min-h-[168px] w-full flex-col justify-between rounded-2xl border border-white/10 border-t-white/20 bg-gradient-to-br from-white/10 to-transparent px-4 py-4 backdrop-blur-md transition-all duration-200 md:min-h-[172px] md:py-5 md:backdrop-blur-xl"
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <div
                          className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10"
                          style={{
                            background: `${node.color}22`,
                            color: node.color,
                            boxShadow: isActiveNode ? `0 0 14px ${node.color}55` : undefined,
                          }}
                        >
                          <Icon size={18} />
                        </div>
                        {isActiveNode && (
                          <span className="flex items-center gap-1 rounded-full border border-cyan-400/40 bg-cyan-500/15 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-cyan-300">
                            <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-cyan-300" />
                            Active
                          </span>
                        )}
                      </div>

                      <p className="mt-3 font-display text-xs font-bold text-white">
                        {node.title}
                      </p>
                      <p className="mt-0.5 text-[11px] font-medium text-slate-400">
                        {node.sub}
                      </p>
                    </div>

                    <div className="mt-3 border-t border-white/10 pt-2.5 text-[10px]">
                      <div className="flex items-center justify-between">
                        <span className="font-medium text-slate-400">Latency</span>
                        <span className="font-mono font-semibold text-white tnum">
                          {node.latency}
                        </span>
                      </div>
                      <p className="mt-1 font-medium" style={{ color: node.color }}>
                        {node.saving}
                      </p>
                    </div>
                  </motion.div>

                  {/* Glowing wire + pulse dot (desktop) */}
                  {idx < PIPELINE_NODES.length - 1 && (
                    <div className="relative hidden w-8 shrink-0 items-center justify-center md:flex">
                      <div className="h-[1.5px] w-full bg-gradient-to-r from-purple-400/25 via-cyan-400/55 to-emerald-400/25" />
                      <svg
                        width="32"
                        height="16"
                        viewBox="0 0 32 16"
                        className="pointer-events-none absolute inset-0 m-auto overflow-visible"
                      >
                        <circle
                          cx="0"
                          cy="8"
                          r="2.8"
                          fill="#22d3ee"
                          style={{ filter: "drop-shadow(0 0 6px #22d3ee)" }}
                        >
                          <animate
                            attributeName="cx"
                            from="0"
                            to="32"
                            dur="1.3s"
                            begin={`${idx * 0.25}s`}
                            repeatCount="indefinite"
                          />
                          <animate
                            attributeName="opacity"
                            values="0;1;1;0"
                            keyTimes="0;0.15;0.85;1"
                            dur="1.3s"
                            begin={`${idx * 0.25}s`}
                            repeatCount="indefinite"
                          />
                        </circle>
                      </svg>
                    </div>
                  )}
                </div>
              );
            })}
          </motion.div>

          {/* Subtle right scroll cue on mobile */}
          <div className="pointer-events-none absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-[#0d0f17] to-transparent md:hidden" />
        </div>
        <p className="mt-1 text-right text-[10px] font-medium text-slate-400 md:hidden">
          Swipe nodes horizontally →
        </p>
      </div>

      {/* 9 Best Practice Status Flips */}
      <div className="card shrink-0 p-4 md:p-5">
        <div className="mb-4 flex items-center justify-between">
          <div>
            <p className="kicker">AWS Well-Architected Framework</p>
            <h3 className="mt-0.5 font-display text-sm font-bold text-white">
              Sustainability + Cost Optimization · Delta Trace (v1 → v2)
            </h3>
          </div>
          <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 font-display text-[11px] font-semibold text-slate-300 tnum">
            {WAR_FINDINGS.length} BPs
          </span>
        </div>

        {/* Mobile Single-Column Accordion (< md) */}
        <div className="flex flex-col gap-2.5 md:hidden">
          {WAR_FINDINGS.map((f) => {
            const expanded = openBp === f.bp;
            return (
              <motion.div
                key={f.bp}
                layout
                className="overflow-hidden rounded-2xl border border-white/10 border-t-white/20 bg-white/[0.04] backdrop-blur-md"
              >
                <button
                  onClick={() => setOpenBp(expanded ? null : f.bp)}
                  className="flex min-h-[52px] w-full items-center justify-between gap-3 px-4 py-3 text-left"
                >
                  <div className="min-w-0 flex-1">
                    <span className="font-mono text-[11px] font-semibold tracking-wider text-slate-400">
                      {f.bp}
                    </span>
                    <p className="truncate text-xs font-semibold text-white">{f.title}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${badgeStyle(f.after)}`}>
                      {f.after}
                    </span>
                    <ChevronDown
                      size={16}
                      className={`text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`}
                    />
                  </div>
                </button>

                <AnimatePresence>
                  {expanded && (
                    <motion.div
                      layout
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      className="border-t border-white/10 px-4 py-3 text-xs"
                    >
                      <p className="mb-2.5 text-slate-300">{f.title}</p>
                      <div className="flex items-center gap-2 text-[10px] font-semibold">
                        <span className={`rounded-full px-2.5 py-0.5 ${badgeStyle(f.before)}`}>
                          Before: {f.before}
                        </span>
                        <ChevronRight size={13} className="text-slate-500" />
                        <span className={`rounded-full px-2.5 py-0.5 ${badgeStyle(f.after)}`}>
                          After: {f.after}
                        </span>
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.div>
            );
          })}
        </div>

        {/* Desktop 3-Column Grid (md+) — strictly untouched */}
        <div className="hidden gap-3.5 md:grid md:grid-cols-2 lg:grid-cols-3">
          {WAR_FINDINGS.map((f, i) => (
            <motion.div
              key={f.bp}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.04 }}
              data-hover="1"
              className="flex flex-col justify-between gap-3 rounded-2xl border border-white/10 border-t-white/20 bg-white/[0.03] p-5 shadow-[0_8px_24px_rgba(0,0,0,0.35)] backdrop-blur-md transition-all duration-200 hover:-translate-y-1 hover:border-white/25 hover:bg-white/[0.06]"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-[11px] font-semibold tracking-wider text-slate-500">
                  {f.bp}
                </span>

                <div className="ml-auto flex items-center gap-1.5 text-[10px] font-semibold">
                  <span className={`rounded-full px-2.5 py-0.5 ${badgeStyle(f.before)}`}>
                    {f.before}
                  </span>
                  <ChevronRight size={13} className="text-slate-600" />
                  <span className={`rounded-full px-2.5 py-0.5 ${badgeStyle(f.after)}`}>
                    {f.after}
                  </span>
                </div>
              </div>

              <p className="text-xs font-medium leading-relaxed text-slate-200">
                {f.title}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </div>
  );
}
