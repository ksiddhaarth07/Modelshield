import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  LayoutDashboard,
  Play,
  Search,
  Settings,
  Shield,
  Sparkles,
  Terminal,
} from "lucide-react";
import { TICKETS } from "../../data/tickets";

export type NavPage = "dashboard" | "replay" | "audit" | "settings";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onNavigate: (page: NavPage) => void;
  onRunReplay: () => void;
  onOpenCustom: () => void;
}

export default function CommandPalette({
  open,
  onClose,
  onNavigate,
  onRunReplay,
  onOpenCustom,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  const actions = useMemo(
    () => [
      {
        id: "nav-dashboard",
        label: "Go to Dashboard",
        hint: "Overview & ROI",
        icon: LayoutDashboard,
        run: () => onNavigate("dashboard"),
      },
      {
        id: "nav-replay",
        label: "Go to Live Split Replay",
        hint: "v1 vs v2 stream",
        icon: Activity,
        run: () => onNavigate("replay"),
      },
      {
        id: "nav-audit",
        label: "Go to Well-Architected Audit",
        hint: "3D Pipeline & 9 BP flips",
        icon: Shield,
        run: () => onNavigate("audit"),
      },
      {
        id: "nav-settings",
        label: "Go to Settings",
        hint: "Endpoints & quotas",
        icon: Settings,
        run: () => onNavigate("settings"),
      },
      {
        id: "act-replay",
        label: "Run 100-Ticket Benchmark Replay",
        hint: "Execute live triage",
        icon: Play,
        run: () => {
          onNavigate("replay");
          onRunReplay();
        },
      },
      {
        id: "act-custom",
        label: "Test Single Custom Ticket",
        hint: "Compare v1 vs v2",
        icon: Terminal,
        run: () => onOpenCustom(),
      },
    ],
    [onNavigate, onOpenCustom, onRunReplay],
  );

  const q = query.trim().toLowerCase();

  const filteredActions = useMemo(
    () =>
      q
        ? actions.filter(
            (a) =>
              a.label.toLowerCase().includes(q) ||
              a.hint.toLowerCase().includes(q),
          )
        : actions,
    [actions, q],
  );

  const matchingTickets = useMemo(() => {
    if (!q) return [];
    return TICKETS.filter(
      (t) =>
        t.ticket_id.toLowerCase().includes(q) ||
        t.subject.toLowerCase().includes(q),
    ).slice(0, 5);
  }, [q]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={onClose}
          className="fixed inset-0 z-[100] flex items-start justify-center bg-black/60 pt-24 backdrop-blur-md"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.96, y: -12 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.96, y: -12 }}
            transition={{ type: "spring", stiffness: 360, damping: 28 }}
            onMouseDown={(e) => e.stopPropagation()}
            className="w-full max-w-xl overflow-hidden rounded-2xl border border-white/15 bg-[#191a2c]/90 shadow-[0_24px_80px_rgba(0,0,0,0.75)] backdrop-blur-2xl"
          >
            {/* Glowing search bar */}
            <div className="flex items-center gap-3 border-b border-white/10 px-4 py-3.5">
              <Search size={16} className="text-neon-cyan" />
              <input
                autoFocus
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Jump to page, search ticket ID (e.g. tkt-031), or run audit..."
                className="w-full bg-transparent text-sm text-white placeholder-slate-500 outline-none"
              />
              <kbd className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] font-medium text-slate-400">
                ESC
              </kbd>
            </div>

            <div className="scroll-thin max-h-80 overflow-y-auto p-2">
              {filteredActions.length > 0 && (
                <div className="mb-2">
                  <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Commands & Navigation
                  </p>
                  {filteredActions.map((item) => {
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.id}
                        data-hover="1"
                        onClick={() => {
                          item.run();
                          onClose();
                        }}
                        className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm text-slate-200 transition-colors hover:bg-white/[0.06]"
                      >
                        <Icon size={15} className="text-neon-cyan" />
                        <span className="flex-1 font-medium">{item.label}</span>
                        <span className="text-[11px] text-slate-500">{item.hint}</span>
                      </button>
                    );
                  })}
                </div>
              )}

              {matchingTickets.length > 0 && (
                <div>
                  <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Benchmark Tickets
                  </p>
                  {matchingTickets.map((t) => (
                    <button
                      key={t.ticket_id}
                      data-hover="1"
                      onClick={() => {
                        onNavigate("replay");
                        onClose();
                      }}
                      className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-xs text-slate-300 transition-colors hover:bg-white/[0.06]"
                    >
                      <Sparkles size={13} className="text-neon-purple" />
                      <span className="font-mono font-semibold text-neon-cyan">
                        {t.ticket_id}
                      </span>
                      <span className="flex-1 truncate">{t.subject}</span>
                      <span className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-400">
                        {t.ground_truth.severity}
                      </span>
                    </button>
                  ))}
                </div>
              )}

              {filteredActions.length === 0 && matchingTickets.length === 0 && (
                <p className="py-8 text-center text-xs text-slate-500">
                  No matching commands or tickets.
                </p>
              )}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
