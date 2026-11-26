import { AnimatePresence, motion } from "framer-motion";
import { LayoutDashboard, Activity, Shield, Settings, ShieldCheck, X } from "lucide-react";

type Page = "dashboard" | "replay" | "audit" | "settings";

interface SidebarProps {
  page: Page;
  onNavigate: (p: Page) => void;
  v1Health: string;
  v2Health: string;
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
}

export const NAV_ITEMS = [
  { id: "dashboard" as Page, label: "Dashboard", shortLabel: "Home", icon: LayoutDashboard },
  { id: "replay" as Page, label: "Live Replay", shortLabel: "Replay", icon: Activity },
  { id: "audit" as Page, label: "WAR Audit", shortLabel: "Audit", icon: Shield },
  { id: "settings" as Page, label: "Settings", shortLabel: "Config", icon: Settings },
];

function SidebarContent({
  page,
  onNavigate,
  v1Health,
  v2Health,
  onCloseMobile,
}: SidebarProps) {
  return (
    <div className="flex h-full flex-col gap-2 px-3.5 py-5">
      {/* Glowing Shield Logo */}
      <div className="mb-4 flex items-center justify-between gap-2.5 px-2">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-neon-cyan/30 bg-neon-cyan/10">
            <Shield
              size={17}
              className="text-[#00f5ff] drop-shadow-[0_0_10px_rgba(0,245,255,0.65)]"
            />
          </div>
          <span className="font-display text-base font-bold tracking-tight text-white">
            ModelShield
          </span>
        </div>

        {onCloseMobile && (
          <button
            onClick={onCloseMobile}
            aria-label="Close navigation menu"
            className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-300 md:hidden"
          >
            <X size={18} />
          </button>
        )}
      </div>

      {/* Nav links */}
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map(({ id, label, icon: Icon }) => {
          const active = page === id;
          return (
            <motion.button
              key={id}
              onClick={() => {
                onNavigate(id);
                onCloseMobile?.();
              }}
              whileHover={{ x: 2 }}
              whileTap={{ scale: 0.96 }}
              data-hover="1"
              className={`flex min-h-[44px] items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors md:min-h-0 ${
                active
                  ? "border border-white/15 border-t-white/25 bg-white/[0.08] text-white shadow-lg backdrop-blur-md"
                  : "text-slate-400 hover:bg-white/[0.03] hover:text-slate-200"
              }`}
            >
              <Icon
                size={16}
                className={active ? "text-[#00f5ff]" : "text-slate-500"}
              />
              {label}
              {active && (
                <motion.div
                  layoutId={onCloseMobile ? "nav-indicator-mobile" : "nav-indicator"}
                  className="ml-auto h-1.5 w-1.5 rounded-full bg-[#00f5ff]"
                  style={{ boxShadow: "0 0 8px #00f5ff" }}
                />
              )}
            </motion.button>
          );
        })}
      </nav>

      {/* Stack health */}
      <div className="mt-2 rounded-2xl border border-white/[0.07] border-t-white/[0.14] bg-white/[0.03] p-3.5 text-xs backdrop-blur-md">
        <p className="mb-2 font-display text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          Stack Health
        </p>
        {[
          { label: "v1 · Nova Pro", status: v1Health },
          { label: "v2 · Nova Lite", status: v2Health },
        ].map(({ label, status }) => {
          const isOk = status === "ok";
          const isDown = status === "down";
          return (
            <div key={label} className="mb-1.5 flex items-center justify-between gap-2 last:mb-0">
              <span className="font-medium text-slate-300">{label}</span>
              <span
                className={`flex items-center gap-1.5 font-semibold tnum ${
                  isOk ? "text-emerald-400" : isDown ? "text-rose-400" : "text-gray-400"
                }`}
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    isOk
                      ? "bg-emerald-400 pulse-dot"
                      : isDown
                        ? "bg-rose-400"
                        : "bg-gray-400 pulse-dot"
                  }`}
                />
                {status}
              </span>
            </div>
          );
        })}
      </div>

      <div className="flex-1" />

      {/* WAR Maturity summary card (from docs/war-after.md) */}
      <motion.div
        whileHover={{ scale: 1.02 }}
        className="rounded-2xl bg-gradient-to-br from-purple-500/40 via-cyan-400/35 to-emerald-400/25 p-[1px] shadow-[0_8px_28px_rgba(6,182,212,0.16)]"
      >
        <div className="relative overflow-hidden rounded-[15px] bg-[#0e121f]/90 p-3.5 backdrop-blur-xl">
          <div className="mb-2.5 flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <ShieldCheck
                size={15}
                className="text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.7)]"
              />
              <span className="font-display text-xs font-bold tracking-wide text-white">
                WAR Maturity
              </span>
            </div>
            <span className="rounded-full border border-emerald-400/40 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300 tnum">
              3 / 5
            </span>
          </div>

          <div className="space-y-1.5 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="font-medium text-slate-400">Cost Opt.</span>
              <span className="font-display font-semibold text-cyan-300 tnum">2 → 3 / 5</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="font-medium text-slate-400">Sustainability</span>
              <span className="font-display font-semibold text-cyan-300 tnum">2 → 3 / 5</span>
            </div>
            <div className="mt-2 flex items-center justify-between gap-2 border-t border-white/10 pt-2">
              <span className="font-medium text-slate-400">High Findings</span>
              <span className="whitespace-nowrap font-display font-bold text-emerald-400 tnum">
                9 → 0
              </span>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

export default function Sidebar(props: SidebarProps) {
  return (
    <>
      {/* Desktop sidebar — strictly untouched */}
      <aside className="hidden h-full w-[210px] shrink-0 md:flex md:flex-col">
        <SidebarContent {...props} onCloseMobile={undefined} />
      </aside>

      {/* Mobile off-canvas glass drawer */}
      <AnimatePresence>
        {props.mobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={props.onCloseMobile}
            className="fixed inset-0 z-50 bg-black/65 backdrop-blur-sm md:hidden"
          >
            <motion.aside
              initial={{ x: "-100%" }}
              animate={{ x: 0 }}
              exit={{ x: "-100%" }}
              transition={{ type: "spring", stiffness: 320, damping: 30 }}
              onClick={(e) => e.stopPropagation()}
              className="h-full w-[260px] border-r border-white/15 bg-[#0e111b]/95 shadow-2xl backdrop-blur-xl"
            >
              <SidebarContent {...props} />
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
