import type { Health, ReplayOutcome, Ticket, TriageResult } from "./types";

const REQUEST_TIMEOUT_MS = 45_000;
const TOKEN_STORAGE_KEY = "modelshield_session_jwt";

let inMemorySessionToken: string | null = null;

export function setSessionToken(token: string | null): void {
  const cleaned = token?.trim() ?? "";
  inMemorySessionToken = cleaned.length > 0 ? cleaned : null;
  try {
    if (inMemorySessionToken) {
      window.sessionStorage.setItem(TOKEN_STORAGE_KEY, inMemorySessionToken);
    } else {
      window.sessionStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // Ignore storage errors in restricted contexts; in-memory token remains active.
  }
}

export function getSessionToken(): string | null {
  if (inMemorySessionToken) return inMemorySessionToken;
  try {
    const stored = window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
    return stored && stored.trim().length > 0 ? stored.trim() : null;
  } catch {
    return null;
  }
}

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
  authToken?: string,
): Promise<TriageResult> {
  return withTimeout(signal, async (inner) => {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = (authToken ?? getSessionToken() ?? "").trim();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    const response = await fetch(`${baseUrl}/triage`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        ticket_id: ticket.ticket_id,
        subject: ticket.subject,
        body: ticket.body,
      }),
      signal: inner,
    });

    const text = await response.text();
    if (!response.ok) {
      throw new ApiError(`triage returned HTTP ${response.status}`, response.status);
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
  authToken?: string;
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
  authToken,
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
        const result = await requestTriage(baseUrl, ticket, signal, authToken);
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
