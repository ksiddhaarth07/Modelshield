import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Cpu,
  Network,
  Server,
  ShieldCheck,
  Sparkles,
  TrendingDown,
} from "lucide-react";
import { int, ms, percent, usd, usdPer10k } from "../../lib/format";
import { reductionPct } from "../../lib/metrics";
import type { RunMetrics, TriageResult } from "../../lib/types";
import AnimatedCounter from "../ui/AnimatedCounter";
import GlassCard from "../ui/GlassCard";

interface DashboardPageProps {
  v1: RunMetrics | null;
  v2: RunMetrics | null;
  v1Results: TriageResult[];
  v2Results: TriageResult[];
  running: boolean;
}

const VOLUME_STEPS = [
  10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000, 2_500_000, 5_000_000,
];

export default function DashboardPage({
  v1,
  v2,
  v1Results,
  v2Results,
  running,
}: DashboardPageProps) {
  const [sliderIdx, setSliderIdx] = useState(2); // 50,000
  const [chartMetric, setChartMetric] = useState<"cost" | "latency">("cost");

  const monthlyTickets = VOLUME_STEPS[sliderIdx] ?? 50_000;
  const sliderPct = (sliderIdx / (VOLUME_STEPS.length - 1)) * 100;

  const v1Cost10k = v1?.costPer10kUsd ?? null;
  const v2Cost10k = v2?.costPer10kUsd ?? null;
  const costDrop = reductionPct(v1Cost10k, v2Cost10k);

  const accuracyPct = v2 ? v2.accuracy * 100 : null;
  const p1RecallPct =
    v2?.p1Recall !== null && v2?.p1Recall !== undefined ? v2.p1Recall * 100 : null;
  const frontierAvoidedPct =
    v1 && v2 && v1.frontierTokens > 0
      ? Math.max(0, (1 - v2.frontierTokens / v1.frontierTokens) * 100)
      : null;
  const computeSavedPct =
    v1 && v2 && v1.gbSeconds > 0
      ? (1 - v2.gbSeconds / v1.gbSeconds) * 100
      : null;

  const v1PerTicket = v1 && v1.attempted > 0 ? v1.totalCostUsd / v1.attempted : null;
  const v2PerTicket = v2 && v2.attempted > 0 ? v2.totalCostUsd / v2.attempted : null;

  const v1Monthly = v1PerTicket !== null ? v1PerTicket * monthlyTickets : null;
  const v2Monthly = v2PerTicket !== null ? v2PerTicket * monthlyTickets : null;
  const annualSavings =
    v1Monthly !== null && v2Monthly !== null
      ? Math.max(0, (v1Monthly - v2Monthly) * 12)
      : null;

  // Route breakdown strictly from measured v2Results
  const routeStats = useMemo(() => {
    const total = v2Results.length;
    const counts = {
      nova_lite: 0,
      cache_hit: 0,
      escalated_pro: 0,
      direct_pro: 0,
    };
    for (const r of v2Results) {
      const rd = r.telemetry?.route_decision;
      if (rd === "nova_lite") counts.nova_lite += 1;
      else if (rd === "cache_hit") counts.cache_hit += 1;
      else if (rd === "escalated_pro" || rd === "fallback_pro") counts.escalated_pro += 1;
      else if (rd === "direct_pro") counts.direct_pro += 1;
    }
    const pctOf = (n: number) => (total > 0 ? Math.round((n / total) * 100) : 0);
    return [
      {
        label: "Nova Lite",
        sub: `${counts.nova_lite} tickets`,
        pct: pctOf(counts.nova_lite),
        color: "#06b6d4",
        glow: "rgba(6,182,212,0.75)",
      },
      {
        label: "Cache Hit",
        sub: `${counts.cache_hit} tickets`,
        pct: pctOf(counts.cache_hit),
        color: "#8b5cf6",
        glow: "rgba(139,92,246,0.75)",
      },
      {
        label: "Escalated Pro",
        sub: `${counts.escalated_pro} tickets`,
        pct: pctOf(counts.escalated_pro),
        color: "#fb923c",
        glow: "rgba(251,146,60,0.75)",
      },
      {
        label: "Direct Pro",
        sub: `${counts.direct_pro} tickets`,
        pct: pctOf(counts.direct_pro),
        color: "#34d399",
        glow: "rgba(52,211,153,0.75)",
      },
    ];
  }, [v2Results]);

  // Live Telemetry chart strictly from measured v1Results & v2Results
  const chartData = useMemo(() => {
    const len = Math.min(v1Results.length, v2Results.length);
    if (len === 0) return [];
    const step = Math.max(1, Math.floor(len / 10));
    const pts = [];
    for (let i = 0; i < len; i += step) {
      const r1 = v1Results[i];
      const r2 = v2Results[i];
      pts.push({
        name: `#${i + 1}`,
        v1:
          chartMetric === "cost"
            ? Number((r1.telemetry.estimated_cost_usd * 1000).toFixed(3))
            : Math.round(r1.telemetry.latency_ms),
        v2:
          chartMetric === "cost"
            ? Number((r2.telemetry.estimated_cost_usd * 1000).toFixed(3))
            : Math.round(r2.telemetry.latency_ms),
      });
    }
    return pts;
  }, [chartMetric, v1Results, v2Results]);

  const ringRadius = 48;
  const ringCirc = 2 * Math.PI * ringRadius;
  const ringFill = frontierAvoidedPct ?? 0;
  const ringOffset = ringCirc - (ringCirc * Math.min(100, ringFill)) / 100;

  return (
    <div className="scroll-thin grid grid-cols-1 gap-3.5 md:h-full md:overflow-y-auto md:pr-1 lg:grid-cols-12">
      {/* CENTER COLUMN (7 cols) */}
      <div className="flex flex-col gap-3.5 lg:col-span-7">
        {/* Clean Hero Status Strip */}
        <GlassCard
          glowColor="rgba(6, 182, 212, 0.22)"
          className="flex flex-col justify-between gap-3 p-4 sm:flex-row sm:flex-wrap sm:items-center md:px-5 md:py-3.5"
        >
          <div className="z-10 min-w-0">
            <p className="kicker text-cyan-300">
              {running ? "Live Benchmark Streaming" : "Measured Benchmark · ap-southeast-2"}
            </p>
            <h2 className="mt-0.5 font-display text-lg font-bold tracking-tight text-white md:text-base">
              Adaptive Nova Lite → Pro Router
            </h2>
          </div>

          <div className="z-10 flex flex-wrap items-center gap-2.5">
            <div className="flex min-h-[38px] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-slate-300 tnum">
              <span
                className={`h-2 w-2 rounded-full ${running ? "pulse-dot bg-cyan-400" : "bg-emerald-400"
                  }`}
              />
              {v2Results.length}/100 Tickets
            </div>

            <div className="flex min-h-[38px] items-center gap-2 rounded-xl border border-emerald-400/30 border-t-white/20 bg-emerald-500/10 px-3 py-1.5 backdrop-blur-md">
              <TrendingDown size={14} className="text-emerald-400" />
              <span className="font-display text-sm font-bold text-emerald-400 tnum">
                {costDrop !== null ? (
                  <>
                    -<AnimatedCounter value={costDrop} decimals={1} suffix="%" />
                  </>
                ) : (
                  "—"
                )}
              </span>
              <span className="text-[10px] font-medium uppercase tracking-wider text-gray-400">
                Spend
              </span>
            </div>
          </div>
        </GlassCard>

        {/* Middle Row: V2 Route Distribution + Frosted V1 / V2 Cards */}
        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-12">
          <GlassCard
            delay={0.05}
            glowColor="rgba(139, 92, 246, 0.2)"
            className="flex flex-col justify-between p-4 md:col-span-5"
          >
            <div className="flex items-center justify-between">
              <h3 className="font-display text-sm font-semibold text-white">
                V2 Route Distribution
              </h3>
              <span className="data-label tnum">{v2Results.length} req</span>
            </div>

            <div className="mt-4 flex flex-1 flex-col justify-center gap-y-4">
              {routeStats.map((item) => (
                <div key={item.label} className="space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <div className="flex min-w-0 items-baseline gap-2">
                      <span className="truncate text-xs font-medium text-slate-200">
                        {item.label}
                      </span>
                      <span className="truncate text-[11px] font-medium text-slate-400 tnum">
                        {item.sub}
                      </span>
                    </div>
                    <span className="w-10 shrink-0 text-right font-display text-xs font-semibold text-white tnum">
                      {item.pct}%
                    </span>
                  </div>

                  <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.max(2, item.pct)}%` }}
                      transition={{ duration: 0.6, ease: "easeOut" }}
                      className="h-full rounded-full"
                      style={{
                        backgroundColor: item.color,
                        boxShadow: `0 0 10px ${item.glow}`,
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </GlassCard>

          {/* V1-BEFORE & V2-AFTER Frosted Glass Cards */}
          <div className="flex flex-col gap-3.5 md:col-span-7">
            <motion.div
              whileHover={{ y: -3, scale: 1.01 }}
              whileTap={{ scale: 0.97 }}
              transition={{ type: "spring", stiffness: 320, damping: 24 }}
              data-hover="1"
              className="relative flex flex-1 flex-col items-center justify-center overflow-hidden rounded-[20px] border border-purple-400/20 border-t-white/25 bg-gradient-to-br from-[#1b152a]/75 via-white/[0.04] to-[#110d1b]/80 px-4 py-4 text-center shadow-[0_12px_36px_rgba(0,0,0,0.5),inset_0_1px_1px_rgba(255,255,255,0.12)] backdrop-blur-md transition-all duration-300 hover:border-purple-400/50 hover:shadow-[0_16px_44px_rgba(0,0,0,0.6),0_0_32px_rgba(139,92,246,0.28)] md:px-6 md:backdrop-blur-3xl"
            >
              <div className="blueprint-grid pointer-events-none absolute inset-0 opacity-[0.05]" />
              <Server
                size={132}
                strokeWidth={1}
                className="pointer-events-none absolute text-purple-300/60 opacity-20"
              />

              <div className="z-10 flex w-full flex-col items-center justify-center gap-3">
                <div className="flex flex-col items-center">
                  <span className="rounded-full border border-purple-400/20 bg-purple-400/10 px-2.5 py-0.5 font-display text-[10px] font-semibold uppercase tracking-wider text-purple-200/90">
                    V1-BEFORE · Single Heavy
                  </span>
                  <p className="mt-1.5 font-display text-xl font-bold tracking-wider text-white">
                    100% NOVA PRO
                  </p>
                </div>

                <div className="h-px w-full bg-gradient-to-r from-transparent via-purple-400/30 to-transparent" />

                <div className="flex w-full items-end justify-between text-left">
                  <div>
                    <p className="data-label">Cost / 10K Tickets</p>
                    <p className="mt-0.5 font-display text-lg font-semibold text-white tnum">
                      {usdPer10k(v1Cost10k)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="data-label">x86_64 · 512 MB · P95</p>
                    <p className="mt-0.5 font-display text-sm font-semibold text-purple-200 tnum">
                      {v1 ? ms(v1.p95LatencyMs) : "—"}
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>

            <motion.div
              whileHover={{ y: -3, scale: 1.01 }}
              whileTap={{ scale: 0.97 }}
              transition={{ type: "spring", stiffness: 320, damping: 24 }}
              data-hover="1"
              className="relative flex flex-1 flex-col items-center justify-center overflow-hidden rounded-[20px] border border-cyan-400/30 border-t-white/30 bg-gradient-to-br from-[#0B3B4A]/70 via-cyan-500/[0.08] to-[#071C26]/80 px-4 py-4 text-center shadow-[0_12px_36px_rgba(0,0,0,0.5),0_0_28px_rgba(6,182,212,0.18),inset_0_1px_1px_rgba(255,255,255,0.18)] backdrop-blur-md transition-all duration-300 hover:border-cyan-300/65 hover:shadow-[0_18px_46px_rgba(0,0,0,0.6),0_0_40px_rgba(6,182,212,0.38)] md:px-6 md:backdrop-blur-3xl"
            >
              <div className="blueprint-grid pointer-events-none absolute inset-0 opacity-[0.05]" />
              <Network
                size={132}
                strokeWidth={1}
                className="pointer-events-none absolute text-cyan-300 opacity-25 drop-shadow-[0_0_20px_rgba(6,182,212,0.6)]"
              />

              <div className="z-10 flex w-full flex-col items-center justify-center gap-3">
                <div className="flex flex-col items-center">
                  <span className="rounded-full border border-cyan-400/35 bg-cyan-400/15 px-2.5 py-0.5 font-display text-[10px] font-semibold uppercase tracking-wider text-cyan-200">
                    V2-AFTER · Adaptive Router
                  </span>
                  <p className="mt-1.5 font-display text-xl font-bold tracking-wider text-white drop-shadow-[0_0_14px_rgba(6,182,212,0.65)]">
                    CACHE → LITE → PRO
                  </p>
                </div>

                <div className="h-px w-full bg-gradient-to-r from-transparent via-cyan-400/50 to-transparent" />

                <div className="flex w-full items-end justify-between text-left">
                  <div>
                    <p className="data-label">Cost / 10K Tickets</p>
                    <p className="mt-0.5 font-display text-lg font-semibold text-cyan-300 drop-shadow-[0_0_10px_rgba(6,182,212,0.5)] tnum">
                      {usdPer10k(v2Cost10k)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="data-label">arm64 · 256 MB · P95</p>
                    <p className="mt-0.5 font-display text-sm font-semibold text-white tnum">
                      {v2 ? ms(v2.p95LatencyMs) : "—"}
                    </p>
                  </div>
                </div>
              </div>
            </motion.div>
          </div>
        </div>

        {/* Bottom Row: Production Scale ROI Calculator */}
        <GlassCard
          delay={0.1}
          glowColor="rgba(52, 211, 153, 0.18)"
          className="p-4"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="kicker">Production Scale ROI</p>
              <p className="mt-0.5 text-xs font-medium text-gray-400">
                Monthly tickets:{" "}
                <span className="font-display text-sm font-semibold text-white tnum">
                  {int(monthlyTickets)}
                </span>
              </p>
            </div>
            <span className="rounded-full border border-emerald-400/35 bg-emerald-500/10 px-3 py-1 font-display text-xs font-semibold text-emerald-400 tnum">
              {annualSavings !== null ? `${usd(annualSavings, 0)} / yr saved` : "—"}
            </span>
          </div>

          <div className="flex min-h-[44px] items-center">
            <input
              type="range"
              min={0}
              max={VOLUME_STEPS.length - 1}
              value={sliderIdx}
              onChange={(e) => setSliderIdx(Number(e.target.value))}
              data-hover="1"
              className="roi-slider w-full"
              style={{
                background: `linear-gradient(to right, #06b6d4 0%, #8b5cf6 ${sliderPct}%, rgba(255,255,255,0.08) ${sliderPct}%, rgba(255,255,255,0.08) 100%)`,
              }}
            />
          </div>

          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="card2 p-3">
              <p className="data-label">v1 / Month</p>
              <p className="mt-1 font-display text-lg font-semibold text-white tnum">
                {usd(v1Monthly, 2)}
              </p>
            </div>
            <div className="card2 p-3">
              <p className="data-label">v2 / Month</p>
              <p className="mt-1 font-display text-lg font-semibold text-cyan-300 tnum">
                {usd(v2Monthly, 2)}
              </p>
            </div>
            <div className="rounded-2xl border border-emerald-400/35 border-t-white/25 bg-emerald-500/[0.08] p-3 shadow-[0_0_20px_rgba(52,211,153,0.12)] backdrop-blur-xl transition-all hover:border-emerald-300/60 hover:shadow-[0_0_26px_rgba(52,211,153,0.28)]">
              <p className="text-[11px] font-medium uppercase tracking-wider text-emerald-400">
                Annual Savings
              </p>
              <p className="mt-1 font-display text-lg font-semibold text-emerald-300 tnum">
                {usd(annualSavings, 0)}
              </p>
            </div>
          </div>
        </GlassCard>
      </div>

      {/* RIGHT COLUMN (5 cols) */}
      <div className="flex flex-col gap-3.5 lg:col-span-5">
        {/* Live Telemetry Chart Card */}
        <GlassCard
          delay={0.06}
          glowColor="rgba(6, 182, 212, 0.18)"
          className="p-4"
        >
          <div className="flex items-center justify-between gap-2">
            <div>
              <h3 className="font-display text-sm font-semibold text-white">
                Live Telemetry
              </h3>
              <p className="data-label">
                {chartMetric === "cost"
                  ? "Per-ticket cost (mUSD)"
                  : "End-to-end latency (ms)"}
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="hidden items-center gap-2.5 text-[10px] font-medium sm:flex">
                <span className="flex items-center gap-1 text-purple-300">
                  <span className="h-2 w-2 rounded-full bg-purple-400" /> v1
                </span>
                <span className="flex items-center gap-1 text-cyan-300">
                  <span className="h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_6px_rgba(6,182,212,0.8)]" />{" "}
                  v2
                </span>
              </div>

              <div className="flex rounded-xl border border-white/10 bg-white/[0.04] p-0.5 text-[11px]">
                {(["cost", "latency"] as const).map((m) => (
                  <button
                    key={m}
                    data-hover="1"
                    onClick={() => setChartMetric(m)}
                    className={`min-h-[38px] rounded-lg px-3 py-1 font-medium capitalize transition-colors md:min-h-0 md:px-2.5 ${chartMetric === m
                      ? "bg-purple-600/80 text-white"
                      : "text-gray-400 hover:text-white"
                      }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="mt-3 w-full overflow-x-auto pb-1">
            <div className="h-44 w-full min-w-[420px] md:min-w-0">
              {chartData.length === 0 ? (
                <div className="flex h-full items-center justify-center text-xs text-slate-400">
                  Waiting for ticket telemetry…
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 12, right: 18, left: 10, bottom: 0 }}>
                    <defs>
                      <linearGradient id="gradV1" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.14} />
                        <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0} />
                      </linearGradient>
                      <linearGradient id="gradV2" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#06b6d4" stopOpacity={0.22} />
                        <stop offset="100%" stopColor="#06b6d4" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid
                      strokeDasharray="3 3"
                      stroke="rgba(255,255,255,0.05)"
                      vertical={false}
                    />
                    <XAxis
                      dataKey="name"
                      padding={{ left: 10, right: 10 }}
                      stroke="#475569"
                      fontSize={9}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      width={40}
                      stroke="#475569"
                      fontSize={9}
                      tickLine={false}
                      axisLine={false}
                    />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "rgba(15, 18, 28, 0.92)",
                        border: "1px solid rgba(255,255,255,0.14)",
                        borderRadius: "12px",
                        fontSize: "11px",
                        color: "#fff",
                        backdropFilter: "blur(12px)",
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="v1"
                      name="v1 (Pro)"
                      stroke="#8b5cf6"
                      strokeWidth={2}
                      fill="url(#gradV1)"
                    />
                    <Area
                      type="monotone"
                      dataKey="v2"
                      name="v2 (Router)"
                      stroke="#06b6d4"
                      strokeWidth={2.5}
                      fill="url(#gradV2)"
                      style={{ filter: "drop-shadow(0 0 10px rgba(6,182,212,0.8))" }}
                      dot={(props) => {
                        const { cx, cy, index } = props as { cx?: number; cy?: number; index?: number };
                        if (index !== chartData.length - 1 || cx === undefined || cy === undefined) {
                          return <g key={`empty-${index}`} />;
                        }
                        return (
                          <g key="live-end-dot">
                            <circle cx={cx} cy={cy} r={6} fill="rgba(6,182,212,0.3)" />
                            <circle cx={cx} cy={cy} r={3.5} fill="#22d3ee" stroke="#ffffff" strokeWidth={1.5} />
                          </g>
                        );
                      }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>
        </GlassCard>

        {/* Thinner Glowing Radial Ring + Clean Single-Icon Legend */}
        <GlassCard
          delay={0.12}
          glowColor="rgba(6, 182, 212, 0.2)"
          className="flex flex-1 flex-col justify-between p-4"
        >
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-display text-sm font-semibold text-white">
                Efficiency & Recall
              </h3>
              <p className="data-label">Frontier tokens avoided</p>
            </div>
            <span
              className={`flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[10px] font-semibold tnum ${
                p1RecallPct !== null
                  ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-300"
                  : "border-white/15 bg-white/[0.05] text-slate-300"
              }`}
            >
              <ShieldCheck size={12} />{" "}
              {p1RecallPct !== null ? `${percent(p1RecallPct, 0)} P1 Recall` : "P1 Pending"}
            </span>
          </div>

          <div className="relative my-2 flex items-center justify-center">
            <div
              className="pointer-events-none absolute h-28 w-28 rounded-full opacity-35 blur-2xl"
              style={{ background: "radial-gradient(circle, #06b6d4, #7c5cfc)" }}
            />

            <div className="relative flex h-36 w-36 items-center justify-center">
              <svg
                className="h-36 w-36 -rotate-90 drop-shadow-[0_0_15px_rgba(6,182,212,0.65)]"
                viewBox="0 0 112 112"
              >
                <defs>
                  <linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#06b6d4" />
                    <stop offset="55%" stopColor="#8b5cf6" />
                    <stop offset="100%" stopColor="#fb923c" />
                  </linearGradient>
                </defs>
                <circle
                  cx="56"
                  cy="56"
                  r={ringRadius}
                  fill="none"
                  stroke="rgba(255,255,255,0.07)"
                  strokeWidth="6"
                />
                <circle
                  cx="56"
                  cy="56"
                  r={ringRadius}
                  fill="none"
                  stroke="url(#ringGrad)"
                  strokeWidth="6"
                  strokeLinecap="round"
                  strokeDasharray={ringCirc}
                  strokeDashoffset={ringOffset}
                />
              </svg>

              <div className="absolute flex h-[92px] w-[92px] flex-col items-center justify-center rounded-full border border-white/15 bg-white/5 shadow-[inset_0_2px_12px_rgba(255,255,255,0.08)] backdrop-blur-sm">
                <p className="font-display text-3xl font-extrabold leading-none text-white tnum">
                  {frontierAvoidedPct !== null ? (
                    <AnimatedCounter value={frontierAvoidedPct} suffix="%" />
                  ) : (
                    "—"
                  )}
                </p>
                <p className="mt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-gray-300">
                  Avoided
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-2.5 border-t border-white/10 pt-3 text-xs">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 font-medium text-gray-300">
                <Sparkles size={13} className="shrink-0 text-cyan-400" />
                <span>Accuracy</span>
              </span>
              <span className="font-display text-sm font-semibold text-white tnum">
                {accuracyPct !== null ? percent(accuracyPct, 1) : "—"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 font-medium text-gray-300">
                <Cpu size={13} className="shrink-0 text-purple-400" />
                <span>Compute (GB-s)</span>
              </span>
              <span className="font-display text-sm font-semibold text-white tnum">
                {v2
                  ? `${v2.gbSeconds.toFixed(1)} GB-s${computeSavedPct !== null ? ` (${computeSavedPct.toFixed(1)}% less)` : ""}`
                  : "—"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 font-medium text-gray-300">
                <ShieldCheck size={13} className="shrink-0 text-emerald-400" />
                <span>P1 Recall Guardrail</span>
              </span>
              <span
                className={`font-display text-sm font-semibold tnum ${
                  p1RecallPct !== null ? "text-emerald-400" : "text-slate-400"
                }`}
              >
                {p1RecallPct !== null ? percent(p1RecallPct, 0) : "Pending"}
              </span>
            </div>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
