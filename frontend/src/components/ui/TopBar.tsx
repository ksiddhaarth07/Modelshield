import { Lock, Menu, Shield, Terminal } from "lucide-react";

const LOGS = [
  "🛡️ [Guardrail] P1 guardrail armed — auto-escalates to Nova Pro for 100% recall",
  "⚡ [Router] Routine triage routed to Nova Lite ($0.06 / $0.24 per 1M tokens)",
  "🗄️ [Cache] DynamoDB 24h TTL cache — normalised SHA-256 key, fail-open",
  "☁️ [Compute] arm64 Graviton 256 MB Lambda — pure stdlib + runtime boto3",
  "🔄 [Reliability] Bedrock retry budget capped at 1+8s × 2 hops (< 20s)",
  "🌏 [API GW] ap-southeast-2 throttle: 25 req/s, burst 50 spend ceiling",
  "📊 [Telemetry] CloudWatch EMF emits exact per-route USD cost & frontier tokens",
  "✅ [WAR] 9 Best Practice flips across Cost Optimization & Sustainability",
];

interface TopBarProps {
  page: string;
  running: boolean;
  progress: number;
  total: number;
  canRun: boolean;
  authenticated: boolean;
  onRun: () => void;
  onOpenCustom: () => void;
  onOpenSettings: () => void;
  onOpenMenu: () => void;
}

export default function TopBar({
  page,
  running,
  progress,
  total,
  canRun,
  authenticated,
  onRun,
  onOpenCustom,
  onOpenSettings,
  onOpenMenu,
}: TopBarProps) {
  const titles: Record<string, string> = {
    dashboard: "Dashboard",
    replay: "Live Split Replay",
    audit: "Well-Architected Audit",
    settings: "Settings",
  };

  const logsStr = LOGS.join("    •    ");

  return (
    <div className="sticky top-0 z-30 flex shrink-0 flex-col bg-[#0d0f17]/80 backdrop-blur-md md:static md:bg-transparent md:backdrop-blur-none">
      {/* Main bar */}
      <div className="flex items-center gap-2.5 px-3 py-2.5 md:gap-3.5 md:px-5 md:py-3">
        {/* Mobile Hamburger */}
        <button
          onClick={onOpenMenu}
          aria-label="Open menu"
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-white/10 bg-white/[0.05] text-slate-200 active:scale-95 md:hidden"
        >
          <Menu size={18} />
        </button>

        {/* Mobile compact Shield badge */}
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-cyan-400/30 bg-cyan-500/10 md:hidden">
          <Shield size={15} className="text-[#00f5ff]" />
        </div>

        <div className="min-w-0 flex-1">
          <h1 className="truncate font-display text-xl font-bold tracking-tight text-white md:text-lg">
            {titles[page] ?? "ModelShield"}
          </h1>
          <p className="hidden text-xs font-medium text-slate-400 sm:block">
            AWS · ap-southeast-2 · Bedrock + Lambda
          </p>
        </div>

        {/* Live status */}
        <div className="hidden items-center gap-1.5 rounded-full border border-emerald-400/35 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-400 sm:flex">
          <span className="pulse-dot h-1.5 w-1.5 rounded-full bg-emerald-400" />
          System Live
        </div>

        {/* Auth session pill */}
        <button
          type="button"
          onClick={onOpenSettings}
          data-hover="1"
          className={`hidden items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold transition-colors sm:flex ${
            authenticated
              ? "border-cyan-400/35 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20"
              : "border-amber-400/35 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20"
          }`}
        >
          <Lock size={11} />
          {authenticated ? "JWT Active" : "Sign In"}
        </button>

        {/* Single primary action pair: Test Single Ticket + Replay 100 Tickets */}
        <button
          onClick={onOpenCustom}
          data-hover="1"
          className="flex min-h-[44px] items-center gap-1.5 rounded-xl border border-white/15 border-t-white/25 bg-white/[0.06] px-3 py-2 text-xs font-medium text-slate-200 backdrop-blur-md transition-colors active:scale-95 hover:bg-white/[0.1] hover:text-white md:min-h-0 md:px-3.5"
        >
          <Terminal size={13} className="text-cyan-300" />
          <span className="hidden sm:inline">Test Single Ticket</span>
          <span className="sm:hidden">Test</span>
        </button>

        {canRun && (
          <button
            onClick={onRun}
            disabled={running}
            data-hover="1"
            className={
              running
                ? "flex min-h-[44px] items-center gap-2 rounded-xl border border-cyan-400/45 border-t-white/30 bg-white/[0.08] px-3 py-2 text-xs font-semibold text-white shadow-[0_0_24px_rgba(6,182,212,0.35)] backdrop-blur-xl tnum md:min-h-0 md:px-4"
                : "min-h-[44px] rounded-xl border border-cyan-300/40 px-3 py-2 text-xs font-semibold text-white shadow-[0_0_22px_rgba(6,182,212,0.45)] transition-all active:scale-95 hover:shadow-[0_0_30px_rgba(6,182,212,0.7)] md:min-h-0 md:px-4"
            }
            style={
              running
                ? undefined
                : { background: "linear-gradient(135deg,#7c5cfc,#06b6d4)" }
            }
          >
            {running && (
              <span className="pulse-dot h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_10px_rgba(6,182,212,1)]" />
            )}
            <span className="hidden sm:inline">
              {running ? `Replaying ${progress}/${total}` : "▶ Replay 100 Tickets"}
            </span>
            <span className="sm:hidden">
              {running ? `${progress}/${total}` : "▶ Replay"}
            </span>
          </button>
        )}
      </div>

      {/* Ticker with horizontal fade mask */}
      <div className="w-full min-w-0 border-y border-white/[0.06] bg-white/[0.02] py-1.5 text-[11px] font-medium text-slate-300/85">
        <div
          className="ticker-mask relative w-full overflow-hidden"
          style={{
            WebkitMaskImage:
              "linear-gradient(to right, transparent 0%, black 6%, black 94%, transparent 100%)",
            maskImage:
              "linear-gradient(to right, transparent 0%, black 6%, black 94%, transparent 100%)",
          }}
        >
          <div className="ticker-track flex w-max gap-10 whitespace-nowrap">
            <span>{logsStr}</span>
            <span aria-hidden>{logsStr}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
