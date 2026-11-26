import type { Health, ReplayOutcome, Ticket, TriageResult } from "./types";

const REQUEST_TIMEOUT_MS = 45_000;

export class ApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function normalizeBaseUrl(url: string | undefined): string | null {
  const trimmed = (url ?? "").trim().replace(/\/+$/, "");
  return trimmed.length > 0 ? trimmed : null;
}

async function withTimeout<T>(
  signal: AbortSignal | undefined,
  run: (signal: AbortSignal) => Promise<T>,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const relay = () => controller.abort();
  signal?.addEventListener("abort", relay);
  try {
    return await run(controller.signal);
  } finally {
    window.clearTimeout(timer);
    signal?.removeEventListener("abort", relay);
  }
}

export async function fetchHealth(baseUrl: string, signal?: AbortSignal): Promise<Health> {
  return withTimeout(signal, async (inner) => {
    const response = await fetch(`${baseUrl}/health`, { signal: inner });
    if (!response.ok) {
      throw new ApiError(`health returned HTTP ${response.status}`, response.status);
    }
    return (await response.json()) as Health;
  });
}

export async function requestTriage(
  baseUrl: string,
  ticket: Pick<Ticket, "ticket_id" | "subject" | "body">,
  signal?: AbortSignal,
): Promise<TriageResult> {
  return withTimeout(signal, async (inner) => {
    const response = await fetch(`${baseUrl}/triage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticket_id: ticket.ticket_id,
        subject: ticket.subject,
        body: ticket.body,
      }),
      signal: inner,
    });

    const text = await response.text();
    if (!response.ok) {
      throw new ApiError(`triage returned HTTP ${response.status}: ${text.slice(0, 180)}`, response.status);
    }
    try {
      return JSON.parse(text) as TriageResult;
    } catch {
      throw new ApiError("triage returned a non-JSON body");
    }
  });
}

interface ReplayOptions {
  baseUrl: string;
  tickets: Ticket[];
  concurrency: number;
  signal?: AbortSignal;
  pacingMs?: number;
  onResult?: (result: TriageResult, completed: number) => void;
  onFailure?: (ticket: Ticket, error: unknown, completed: number) => void;
}

/** Spaces request starts so the Bedrock per-minute quota is never hit. */
class Pacer {
  private next = 0;

  constructor(private readonly intervalMs: number) {}

  async wait(): Promise<void> {
    if (this.intervalMs <= 0) return;
    const now = Date.now();
    const delay = Math.max(0, this.next - now);
    this.next = Math.max(now, this.next) + this.intervalMs;
    if (delay > 0) {
      await new Promise((resolve) => window.setTimeout(resolve, delay));
    }
  }
}

/**
 * Replays tickets through one stack with a hard in-flight cap. The cap is the
 * whole point: 100 concurrent Bedrock calls would throttle on camera.
 */
export async function replayStack({
  baseUrl,
  tickets,
  concurrency,
  signal,
  pacingMs = 2000,
  onResult,
  onFailure,
}: ReplayOptions): Promise<ReplayOutcome> {
  const safeConcurrency = Math.max(1, Math.min(2, concurrency));
  const safePacingMs = Math.max(1500, pacingMs);
  const queue = [...tickets];
  const results: TriageResult[] = [];
  const pacer = new Pacer(safePacingMs);
  let failures = 0;
  let completed = 0;

  const worker = async (): Promise<void> => {
    while (queue.length > 0) {
      if (signal?.aborted) return;
      const ticket = queue.shift();
      if (!ticket) return;
      try {
        await pacer.wait();
        const result = await requestTriage(baseUrl, ticket, signal);
        results.push(result);
        completed += 1;
        onResult?.(result, completed);
      } catch (error) {
        failures += 1;
        completed += 1;
        onFailure?.(ticket, error, completed);
      }
    }
  };

  const workers = Array.from(
    { length: Math.max(1, Math.min(safeConcurrency, tickets.length)) },
    () => worker(),
  );
  await Promise.all(workers);

  return { results, failures };
}
