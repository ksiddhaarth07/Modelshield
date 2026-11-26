import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import CustomTicketDrawer from "./components/CustomTicketDrawer";
import CommandPalette, { type NavPage } from "./components/ui/CommandPalette";
import CustomCursor from "./components/ui/CustomCursor";
import Sidebar, { NAV_ITEMS } from "./components/ui/Sidebar";
import TopBar from "./components/ui/TopBar";
import DashboardPage from "./components/pages/DashboardPage";
import LiveReplayPage from "./components/pages/LiveReplayPage";
import SettingsPage from "./components/pages/SettingsPage";
import WarAuditPage from "./components/pages/WarAuditPage";
import { TICKETS } from "./data/tickets";
import { INITIAL_V1_RESULTS, INITIAL_V2_RESULTS } from "./data/benchmark";
import { ApiError, fetchHealth, getSessionToken, normalizeBaseUrl, parseTokenMeta, replayStack, requestTriage } from "./lib/api";
import { summarize } from "./lib/metrics";
import type { HealthState, TriageResult } from "./lib/types";

const V1_BASE = normalizeBaseUrl(import.meta.env.VITE_V1_API_URL);
const V2_BASE = normalizeBaseUrl(import.meta.env.VITE_V2_API_URL);

type CustomResults = { v1: TriageResult | string | null; v2: TriageResult | string | null };

export default function App() {
  const [page, setPage] = useState<NavPage>("dashboard");
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [v1Results, setV1Results] = useState<TriageResult[]>(INITIAL_V1_RESULTS);
  const [v2Results, setV2Results] = useState<TriageResult[]>(INITIAL_V2_RESULTS);
  const [failures, setFailures] = useState<{ v1: string[]; v2: string[] }>({ v1: [], v2: [] });
  const [running, setRunning] = useState(false);
  const [health, setHealth] = useState<{ v1: HealthState; v2: HealthState }>({
    v1: "unknown",
    v2: "unknown",
  });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [customLoading, setCustomLoading] = useState(false);
  const [customResults, setCustomResults] = useState<CustomResults>({ v1: null, v2: null });
  const [authPrompt, setAuthPrompt] = useState<string | null>(null);
  const [authenticated, setAuthenticated] = useState(() => {
    const token = getSessionToken();
    const meta = parseTokenMeta(token);
    return Boolean(token && !meta?.expired);
  });
  const [mouseOffset, setMouseOffset] = useState({ x: 0, y: 0 });
  const abortRef = useRef<AbortController | null>(null);

  const refreshAuthState = () => {
    const token = getSessionToken();
    const meta = parseTokenMeta(token);
    const ok = Boolean(token && !meta?.expired);
    setAuthenticated(ok);
    if (ok) setAuthPrompt(null);
  };

  // Cmd+K / Ctrl+K listener
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdOpen((o) => !o);
      }
      if (e.key === "Escape") {
        setCmdOpen(false);
        setMobileMenuOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Subtle parallax for ambient aurora orbs (desktop pointer only)
  useEffect(() => {
    if (window.matchMedia("(pointer: coarse)").matches) return;
    const onMove = (e: MouseEvent) => {
      const nx = (e.clientX / window.innerWidth - 0.5) * 24;
      const ny = (e.clientY / window.innerHeight - 0.5) * 24;
      setMouseOffset({ x: nx, y: ny });
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, []);

  // Health polling
  useEffect(() => {
    let active = true;
    const check = async () => {
      const next: { v1: HealthState; v2: HealthState } = { v1: "unknown", v2: "unknown" };
      if (!V1_BASE) next.v1 = "unconfigured";
      else {
        try {
          await fetchHealth(V1_BASE);
          next.v1 = "ok";
        } catch {
          next.v1 = "down";
        }
      }
      if (!V2_BASE) next.v2 = "unconfigured";
      else {
        try {
          await fetchHealth(V2_BASE);
          next.v2 = "ok";
        } catch {
          next.v2 = "down";
        }
      }
      if (active) setHealth(next);
    };
    void check();
    const timer = window.setInterval(check, 20_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const truth = useMemo(() => new Map(TICKETS.map((t) => [t.ticket_id, t])), []);
  const v1Metrics = useMemo(
    () =>
      v1Results.length + failures.v1.length > 0
        ? summarize(v1Results, truth, failures.v1.length, failures.v1)
        : null,
    [v1Results, truth, failures.v1],
  );
  const v2Metrics = useMemo(
    () =>
      v2Results.length + failures.v2.length > 0
        ? summarize(v2Results, truth, failures.v2.length, failures.v2)
        : null,
    [v2Results, truth, failures.v2],
  );

  const progress = Math.max(
    v1Results.length + failures.v1.length,
    v2Results.length + failures.v2.length,
    0,
  );
  const canRun = V1_BASE !== null && V2_BASE !== null;

  const runReplay = async () => {
    if (!V1_BASE || !V2_BASE || running) return;
    const token = getSessionToken();
    const meta = parseTokenMeta(token);
    if (!token || meta?.expired) {
      setAuthPrompt("Sign in with Cognito (or paste a Bearer JWT) before running live replay requests.");
      setPage("settings");
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setV1Results([]);
    setV2Results([]);
    setFailures({ v1: [], v2: [] });

    try {
      await Promise.all([
        replayStack({
          baseUrl: V1_BASE,
          tickets: TICKETS,
          concurrency: 2,
          signal: controller.signal,
          onResult: (r) => setV1Results((prev) => [...prev, r]),
          onFailure: (ticket) =>
            setFailures((prev) => ({ ...prev, v1: [...prev.v1, ticket.ticket_id] })),
        }),
        replayStack({
          baseUrl: V2_BASE,
          tickets: TICKETS,
          concurrency: 2,
          signal: controller.signal,
          onResult: (r) => setV2Results((prev) => [...prev, r]),
          onFailure: (ticket) =>
            setFailures((prev) => ({ ...prev, v2: [...prev.v2, ticket.ticket_id] })),
        }),
      ]);
    } finally {
      abortRef.current = null;
      setRunning(false);
    }
  };

  const submitCustom = async (subject: string, body: string) => {
    if (!V1_BASE || !V2_BASE) return;
    setCustomLoading(true);
    setCustomResults({ v1: null, v2: null });
    const ticket = { ticket_id: `tkt-custom-${Date.now()}`, subject, body };
    const settle = async (baseUrl: string): Promise<TriageResult | string> => {
      try {
        return await requestTriage(baseUrl, ticket);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          return "HTTP 401 Unauthorized — sign in with Cognito under Settings first.";
        }
        return err instanceof Error ? err.message : "request failed";
      }
    };
    try {
      const [v1, v2] = await Promise.all([settle(V1_BASE), settle(V2_BASE)]);
      setCustomResults({ v1, v2 });
    } finally {
      setCustomLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen w-screen bg-[#080a10] text-white md:h-screen md:overflow-hidden">
      <CustomCursor />

      {/* Huge blurred floating radial background orbs */}
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div
          className="absolute -right-28 -top-32 h-[420px] w-[420px] rounded-full opacity-20 blur-[100px] transition-transform duration-300 md:h-[640px] md:w-[640px] md:opacity-25 md:blur-[140px]"
          style={{
            background: "radial-gradient(circle, rgba(6,182,212,0.9) 0%, rgba(14,116,144,0.3) 55%, transparent 75%)",
            transform: `translate(${-mouseOffset.x}px, ${mouseOffset.y}px)`,
          }}
        />
        <div
          className="absolute -bottom-36 -left-32 h-[440px] w-[440px] rounded-full opacity-25 blur-[110px] transition-transform duration-300 md:h-[660px] md:w-[660px] md:opacity-30 md:blur-[140px]"
          style={{
            background: "radial-gradient(circle, rgba(124,58,237,0.9) 0%, rgba(88,28,135,0.35) 55%, transparent 75%)",
            transform: `translate(${mouseOffset.x}px, ${-mouseOffset.y}px)`,
          }}
        />
        <div
          className="hidden md:block absolute left-1/3 top-0 h-[360px] w-[360px] rounded-full opacity-15 blur-[130px]"
          style={{
            background: "radial-gradient(circle, rgba(56,189,248,0.6) 0%, transparent 70%)",
          }}
        />
      </div>

      {/* Whole-screen subtle noise overlay */}
      <div className="app-noise pointer-events-none fixed inset-0 z-20" />

      {/* Main Translucent Glass Shell */}
      <div className="relative z-10 flex w-full p-0 md:h-full md:p-3">
        <div className="flex min-h-screen w-full overflow-visible bg-white/[0.015] md:h-full md:min-h-0 md:overflow-hidden md:rounded-[28px] md:border md:border-white/10 md:border-t-white/20 md:bg-white/[0.025] md:shadow-2xl md:backdrop-blur-2xl">
          <Sidebar
            page={page}
            onNavigate={setPage}
            v1Health={health.v1}
            v2Health={health.v2}
            mobileOpen={mobileMenuOpen}
            onCloseMobile={() => setMobileMenuOpen(false)}
          />

          <div className="flex min-w-0 flex-1 flex-col md:border-l md:border-white/[0.05]">
            <TopBar
              page={page}
              running={running}
              progress={progress}
              total={TICKETS.length}
              canRun={canRun}
              authenticated={authenticated}
              onRun={() => void runReplay()}
              onOpenCustom={() => setDrawerOpen(true)}
              onOpenSettings={() => setPage("settings")}
              onOpenMenu={() => setMobileMenuOpen(true)}
            />

            <main className="min-h-0 flex-1 p-3.5 pb-24 md:overflow-y-auto md:overflow-x-hidden md:p-4 md:pb-4">
              <AnimatePresence mode="wait">
                <motion.div
                  key={page}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.22 }}
                  className="md:h-full"
                >
                  {page === "dashboard" && (
                    <DashboardPage
                      v1={v1Metrics}
                      v2={v2Metrics}
                      v1Results={v1Results}
                      v2Results={v2Results}
                      running={running}
                    />
                  )}
                  {page === "replay" && (
                    <LiveReplayPage
                      v1={v1Results}
                      v2={v2Results}
                      running={running}
                      progress={progress}
                      total={TICKETS.length}
                    />
                  )}
                  {page === "audit" && <WarAuditPage />}
                  {page === "settings" && (
                    <SettingsPage
                      v1Url={V1_BASE}
                      v2Url={V2_BASE}
                      authPrompt={authPrompt}
                      onAuthChange={refreshAuthState}
                      onOpenCustom={() => setDrawerOpen(true)}
                    />
                  )}
                </motion.div>
              </AnimatePresence>
            </main>
          </div>
        </div>
      </div>

      {/* Fixed Mobile Bottom Navigation Bar */}
      <nav
        aria-label="Mobile navigation"
        className="fixed inset-x-3 bottom-3 z-40 flex items-center justify-around rounded-2xl border border-white/15 border-t-white/25 bg-[#0e111b]/90 px-2 py-1.5 shadow-[0_12px_36px_rgba(0,0,0,0.65)] backdrop-blur-lg md:hidden"
      >
        {NAV_ITEMS.map(({ id, shortLabel, icon: Icon }) => {
          const active = page === id;
          return (
            <motion.button
              key={id}
              whileTap={{ scale: 0.92 }}
              onClick={() => setPage(id)}
              className={`flex min-h-[44px] min-w-[60px] flex-col items-center justify-center gap-0.5 rounded-xl px-3 py-1 text-[11px] font-medium transition-colors ${active ? "bg-white/[0.08] text-cyan-300" : "text-slate-400"
                }`}
            >
              <Icon size={17} className={active ? "text-[#00f5ff]" : "text-slate-400"} />
              <span>{shortLabel}</span>
            </motion.button>
          );
        })}
      </nav>

      <CommandPalette
        open={cmdOpen}
        onClose={() => setCmdOpen(false)}
        onNavigate={setPage}
        onRunReplay={() => void runReplay()}
        onOpenCustom={() => setDrawerOpen(true)}
      />

      <CustomTicketDrawer
        open={drawerOpen}
        loading={customLoading}
        results={customResults}
        onClose={() => setDrawerOpen(false)}
        onSubmit={(subject, body) => void submitCustom(subject, body)}
      />
    </div>
  );
}
