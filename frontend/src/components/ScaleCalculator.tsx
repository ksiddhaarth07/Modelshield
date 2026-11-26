import { useState } from "react";
import { int, usd } from "../lib/format";
import type { RunMetrics } from "../lib/types";

const VOLUMES = [10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000, 2_500_000, 5_000_000];
const LABELS = ["10K", "25K", "50K", "100K", "250K", "500K", "1M", "2.5M", "5M"];

interface ScaleCalculatorProps {
  v1: RunMetrics | null;
  v2: RunMetrics | null;
}

export default function ScaleCalculator({ v1, v2 }: ScaleCalculatorProps) {
  const [index, setIndex] = useState(3);
  const volume = VOLUMES[index];
  const ready = v1 !== null && v2 !== null;

  const perTicketV1 = ready ? v1.costPer10kUsd / 10_000 : null;
  const perTicketV2 = ready ? v2.costPer10kUsd / 10_000 : null;
  const monthlyV1 = perTicketV1 !== null ? perTicketV1 * volume : null;
  const monthlyV2 = perTicketV2 !== null ? perTicketV2 * volume : null;
  const annualSavings = monthlyV1 !== null && monthlyV2 !== null ? (monthlyV1 - monthlyV2) * 12 : null;
  const reduction =
    monthlyV1 !== null && monthlyV2 !== null && monthlyV1 > 0
      ? ((1 - monthlyV2 / monthlyV1) * 100).toFixed(1)
      : null;

  return (
    <section className="glass flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="kicker">Production scale ROI</p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            Measured per-ticket cost, multiplied by your monthly volume
          </p>
        </div>
        {reduction ? (
          <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[10px] font-semibold text-emerald-700 tnum">
            −{reduction}% spend
          </span>
        ) : null}
      </div>

      <div>
        <div className="flex items-baseline justify-between">
          <span className="text-[11px] font-medium text-slate-600">Tickets / month</span>
          <span className="text-sm font-semibold tracking-tight tnum">{int(volume)}</span>
        </div>
        <input
          type="range"
          min={0}
          max={VOLUMES.length - 1}
          step={1}
          value={index}
          disabled={!ready}
          onChange={(event) => setIndex(Number(event.target.value))}
          className="mt-2 w-full accent-slate-900 disabled:opacity-40"
          aria-label="Monthly ticket volume"
        />
        <div className="mt-1 flex justify-between text-[9px] font-medium text-slate-400 tnum">
          {LABELS.map((label, position) => (
            <span key={label} className={position === index ? "text-slate-700" : ""}>
              {label}
            </span>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-xl border border-slate-200/70 bg-white/60 p-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">v1 / month</p>
          <p className="mt-1 text-[13px] font-semibold tracking-tight tnum">{usd(monthlyV1, 2)}</p>
        </div>
        <div className="rounded-xl border border-slate-200/70 bg-white/60 p-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">v2 / month</p>
          <p className="mt-1 text-[13px] font-semibold tracking-tight tnum">{usd(monthlyV2, 2)}</p>
        </div>
        <div className="rounded-xl border border-emerald-200/70 bg-emerald-50/60 p-2.5">
          <p className="text-[9px] font-semibold uppercase tracking-wide text-emerald-700/70">
            Annual savings
          </p>
          <p className="mt-1 text-[13px] font-semibold tracking-tight text-emerald-800 tnum">
            {usd(annualSavings, 0)}
          </p>
        </div>
      </div>

      {!ready ? (
        <p className="text-[10px] text-slate-400">
          Run the 100-ticket replay to unlock the slider with measured unit economics.
        </p>
      ) : null}
    </section>
  );
}
