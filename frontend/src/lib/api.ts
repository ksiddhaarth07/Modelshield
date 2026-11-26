import type { Health, ReplayOutcome, Ticket, TriageResult } from "./types";

const REQUEST_TIMEOUT_MS = 45_000;
const TOKEN_STORAGE_KEY = "modelshield_session_jwt";
const CLIENT_ID_STORAGE_KEY = "modelshield_cognito_client_id";
const AWS_REGION_RE = /^[a-z]{2}(?:-[a-z]+)+-\d+$/;

let inMemorySessionToken: string | null = null;

export interface TokenMeta {
  sub?: string;
  email?: string;
  tenantId?: string;
  exp?: number;
  expired: boolean;
}

export type CognitoSignInResult =
  | { status: "authenticated"; idToken: string }
  | { status: "new_password_required"; session: string };

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

export function getSavedCognitoClientId(): string {
  const envClientId = (import.meta.env.VITE_COGNITO_CLIENT_ID ?? "").trim();
  try {
    const stored = window.sessionStorage.getItem(CLIENT_ID_STORAGE_KEY);
    if (stored && stored.trim().length > 0) return stored.trim();
  } catch {
    // Ignore storage read errors.
  }
  return envClientId;
}

export function setSavedCognitoClientId(clientId: string): void {
  const cleaned = clientId.trim();
  try {
    if (cleaned) {
      window.sessionStorage.setItem(CLIENT_ID_STORAGE_KEY, cleaned);
    } else {
      window.sessionStorage.removeItem(CLIENT_ID_STORAGE_KEY);
    }
  } catch {
    // Ignore storage write errors.
  }
}

export function parseTokenMeta(token: string | null): TokenMeta | null {
  if (!token) return null;
  const parts = token.split(".");
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const normalized = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
    const payload = JSON.parse(window.atob(padded)) as Record<string, unknown>;
    const exp = typeof payload.exp === "number" ? payload.exp : undefined;
    const expired = typeof exp === "number" ? exp * 1000 <= Date.now() : false;
    const rawTenant = payload["custom:tenant_id"] ?? payload.tenant_id;
    return {
      sub: typeof payload.sub === "string" ? payload.sub : undefined,
      email: typeof payload.email === "string" ? payload.email : undefined,
      tenantId: typeof rawTenant === "string" ? rawTenant : undefined,
      exp,
      expired,
    };
  } catch {
    return null;
  }
}

function resolveCognitoEndpoint(region: string): string {
  const cleaned = region.trim().toLowerCase();
  if (!AWS_REGION_RE.test(cleaned)) {
    throw new ApiError("Invalid AWS Cognito region format.");
  }
  return `https://cognito-idp.${cleaned}.amazonaws.com/`;
}

async function callCognitoIdp(
  region: string,
  target: "InitiateAuth" | "RespondToAuthChallenge",
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const endpoint = resolveCognitoEndpoint(region);
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-amz-json-1.1",
      "X-Amz-Target": `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(payload),
  });
  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    const msg =
      typeof data.message === "string"
        ? data.message
        : `Cognito returned HTTP ${response.status}`;
    throw new ApiError(msg, response.status);
  }
  return data;
}

export async function signInWithCognito(params: {
  email: string;
  password: string;
  clientId: string;
  region?: string;
}): Promise<CognitoSignInResult> {
  const region = params.region ?? import.meta.env.VITE_COGNITO_REGION ?? "ap-southeast-2";
  const clientId = params.clientId.trim();
  if (!clientId) throw new ApiError("Cognito App Client ID is required.");
  const data = await callCognitoIdp(region, "InitiateAuth", {
    AuthFlow: "USER_PASSWORD_AUTH",
    ClientId: clientId,
    AuthParameters: {
      USERNAME: params.email.trim(),
      PASSWORD: params.password,
    },
  });
  if (data.ChallengeName === "NEW_PASSWORD_REQUIRED" && typeof data.Session === "string") {
    return { status: "new_password_required", session: data.Session };
  }
  const authResult = data.AuthenticationResult as Record<string, unknown> | undefined;
  const idToken = typeof authResult?.IdToken === "string" ? authResult.IdToken : "";
  if (!idToken) {
    throw new ApiError("Cognito did not return an ID token.");
  }
  setSavedCognitoClientId(clientId);
  setSessionToken(idToken);
  return { status: "authenticated", idToken };
}

export async function completeCognitoNewPassword(params: {
  email: string;
  newPassword: string;
  session: string;
  clientId: string;
  region?: string;
}): Promise<string> {
  const region = params.region ?? import.meta.env.VITE_COGNITO_REGION ?? "ap-southeast-2";
  const clientId = params.clientId.trim();
  const data = await callCognitoIdp(region, "RespondToAuthChallenge", {
    ChallengeName: "NEW_PASSWORD_REQUIRED",
    ClientId: clientId,
    Session: params.session,
    ChallengeResponses: {
      USERNAME: params.email.trim(),
      NEW_PASSWORD: params.newPassword,
    },
  });
  const authResult = data.AuthenticationResult as Record<string, unknown> | undefined;
  const idToken = typeof authResult?.IdToken === "string" ? authResult.IdToken : "";
  if (!idToken) {
    throw new ApiError("Cognito challenge did not return an ID token.");
  }
  setSavedCognitoClientId(clientId);
  setSessionToken(idToken);
  return idToken;
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
