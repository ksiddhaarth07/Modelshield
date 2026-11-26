import { useEffect, useMemo, useRef, useState } from "react";
import CustomTicketDrawer from "./components/CustomTicketDrawer";
import HeaderBar from "./components/HeaderBar";
import LiveTickerSplit from "./components/LiveTickerSplit";
import MetricsHeroGrid from "./components/MetricsHeroGrid";
import ScaleCalculator from "./components/ScaleCalculator";
import WarScorecard from "./components/WarScorecard";
import { TICKETS } from "./data/tickets";
import { WAR_FINDINGS } from "./data/war";
import { fetchHealth, normalizeBaseUrl, replayStack, requestTriage } from "./lib/api";
import { summarize } from "./lib/metrics";
import type { HealthState, TriageResult } from "./lib/types";

const V1_BASE = normalizeBaseUrl(import.meta.env.VITE_V1_API_URL);
const V2_BASE = normalizeBaseUrl(import.meta.env.VITE_V2_API_URL);

type CustomResults = { v1: TriageResult | string | null; v2: TriageResult | string | null };

export default function App() {
  const [v1Results, setV1Results] = useState<TriageResult[]>([]);
  const [v2Results, setV2Results] = useState<TriageResult[]>([]);
  const [failures, setFailures] = useState({ v1: 0, v2: 0 });
  const [running, setRunning] = useState(false);
  const [health, setHealth] = useState<{ v1: HealthState; v2: HealthState }>({
    v1: "unknown",
    v2: "unknown",
  });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [customLoading, setCustomLoading] = useState(false);
  const [customResults, setCustomResults] = useState<CustomResults>({ v1: null, v2: null });
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let active = true;

    const check = async () => {
      const next: { v1: HealthState; v2: HealthState } = { v1: "unknown", v2: "unknown" };

      if (!V1_BASE) {
        next.v1 = "unconfigured";
      } else {
        try {
          await fetchHealth(V1_BASE);
          next.v1 = "ok";
        } catch {
          next.v1 = "down";
        }
      }

      if (!V2_BASE) {
        next.v2 = "unconfigured";
      } else {
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

  const truth = useMemo(() => new Map(TICKETS.map((ticket) => [ticket.ticket_id, ticket])), []);

  const v1Metrics = useMemo(
    () => (v1Results.length > 0 ? summarize(v1Results, truth, failures.v1) : null),
    [v1Results, truth, failures.v1],
  );
  const v2Metrics = useMemo(
    () => (v2Results.length > 0 ? summarize(v2Results, truth, failures.v2) : null),
    [v2Results, truth, failures.v2],
  );

  const progress = Math.max(
    v1Results.length + failures.v1,
    v2Results.length + failures.v2,
    0,
  );
  const canRun = V1_BASE !== null && V2_BASE !== null;

  const runReplay = async () => {
    if (!V1_BASE || !V2_BASE || running) return;

    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setV1Results([]);
    setV2Results([]);
    setFailures({ v1: 0, v2: 0 });

    try {
      await Promise.all([
        replayStack({
          baseUrl: V1_BASE,
          tickets: TICKETS,
          concurrency: 4,
          signal: controller.signal,
          onResult: (result) => setV1Results((previous) => [...previous, result]),
          onFailure: () => setFailures((previous) => ({ ...previous, v1: previous.v1 + 1 })),
        }),
        replayStack({
          baseUrl: V2_BASE,
          tickets: TICKETS,
          concurrency: 4,
          signal: controller.signal,
          onResult: (result) => setV2Results((previous) => [...previous, result]),
          onFailure: () => setFailures((previous) => ({ ...previous, v2: previous.v2 + 1 })),
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
      } catch (error) {
        return error instanceof Error ? error.message : "request failed";
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
    <div className="mesh min-h-screen xl:h-screen xl:overflow-hidden">
      <div className="mx-auto flex h-full max-w-[1560px] flex-col gap-3 p-3 xl:p-4">
        <HeaderBar
          v1Health={health.v1}
          v2Health={health.v2}
          running={running}
          progress={progress}
          total={TICKETS.length}
          canRun={canRun}
          onRun={() => void runReplay()}
          onOpenCustom={() => setDrawerOpen(true)}
        />

        <MetricsHeroGrid v1={v1Metrics} v2={v2Metrics} running={running} />

        <LiveTickerSplit
          v1={v1Results}
          v2={v2Results}
          running={running}
          progress={progress}
          total={TICKETS.length}
        />

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <ScaleCalculator v1={v1Metrics} v2={v2Metrics} />
          <WarScorecard findings={WAR_FINDINGS} />
        </div>
      </div>

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
