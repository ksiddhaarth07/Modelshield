import { useState, type FormEvent } from "react";
import { CheckCircle2, Globe, KeyRound, Lock, LogOut, Shield, Sliders, Terminal } from "lucide-react";
import {
  completeCognitoNewPassword,
  getSavedCognitoClientId,
  getSessionToken,
  parseTokenMeta,
  setSessionToken,
  signInWithCognito,
} from "../../lib/api";

interface SettingsPageProps {
  v1Url: string | null;
  v2Url: string | null;
  authPrompt?: string | null;
  onAuthChange?: () => void;
  onOpenCustom: () => void;
}

export default function SettingsPage({
  v1Url,
  v2Url,
  authPrompt,
  onAuthChange,
  onOpenCustom,
}: SettingsPageProps) {
  const [authMode, setAuthMode] = useState<"cognito" | "token">("cognito");
  const [clientId, setClientId] = useState(() => getSavedCognitoClientId());
  const [region, setRegion] = useState(() => (import.meta.env.VITE_COGNITO_REGION ?? "ap-southeast-2").trim());
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [challengeSession, setChallengeSession] = useState<string | null>(null);
  const [manualToken, setManualToken] = useState("");
  const [authLoading, setAuthLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authSuccess, setAuthSuccess] = useState<string | null>(null);
  const [activeToken, setActiveToken] = useState<string | null>(() => getSessionToken());

  const tokenMeta = parseTokenMeta(activeToken);
  const isAuthenticated = Boolean(activeToken && !tokenMeta?.expired);

  const syncTokenState = () => {
    setActiveToken(getSessionToken());
    onAuthChange?.();
  };

  const handleCognitoSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setAuthError(null);
    setAuthSuccess(null);
    setAuthLoading(true);
    try {
      if (challengeSession) {
        await completeCognitoNewPassword({
          email,
          newPassword,
          session: challengeSession,
          clientId,
          region,
        });
        setChallengeSession(null);
        setPassword("");
        setNewPassword("");
        setAuthSuccess("Password updated and Cognito session activated.");
        syncTokenState();
      } else {
        const result = await signInWithCognito({ email, password, clientId, region });
        if (result.status === "new_password_required") {
          setChallengeSession(result.session);
          setAuthSuccess("Temporary password accepted. Enter a new 12+ character password to activate.");
        } else {
          setPassword("");
          setAuthSuccess("Cognito JWT acquired and stored in sessionStorage.");
          syncTokenState();
        }
      }
    } catch (err) {
      setAuthError(err instanceof Error ? err.message : "Cognito sign-in failed.");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleSaveManualToken = (event: FormEvent) => {
    event.preventDefault();
    setAuthError(null);
    setAuthSuccess(null);
    const cleaned = manualToken.trim().replace(/^Bearer\s+/i, "");
    if (!cleaned || cleaned.split(".").length !== 3) {
      setAuthError("Enter a valid 3-segment JWT token.");
      return;
    }
    setSessionToken(cleaned);
    setManualToken("");
    setAuthSuccess("Bearer JWT saved to sessionStorage.");
    syncTokenState();
  };

  const handleSignOut = () => {
    setSessionToken(null);
    setChallengeSession(null);
    setAuthError(null);
    setAuthSuccess("Session token cleared.");
    syncTokenState();
  };

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <div className="card p-5 lg:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 text-neon-cyan">
            <Lock size={16} />
            <h3 className="text-sm font-bold text-white">Cognito JWT Authentication</h3>
          </div>
          <div className="flex items-center gap-2">
            {isAuthenticated ? (
              <span className="flex items-center gap-1.5 rounded-full border border-emerald-400/35 bg-emerald-500/10 px-3 py-1 text-[11px] font-semibold text-emerald-300">
                <CheckCircle2 size={12} />
                Authenticated{tokenMeta?.email ? ` · ${tokenMeta.email}` : ""}
              </span>
            ) : (
              <span className="rounded-full border border-amber-400/35 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold text-amber-300">
                {tokenMeta?.expired ? "Session Expired" : "Not Signed In (Public /health only)"}
              </span>
            )}
            {activeToken && (
              <button
                type="button"
                onClick={handleSignOut}
                data-hover="1"
                className="flex items-center gap-1 rounded-lg border border-white/15 bg-white/[0.05] px-2.5 py-1 text-[11px] text-slate-200 hover:bg-white/10"
              >
                <LogOut size={12} /> Sign Out
              </button>
            )}
          </div>
        </div>

        <p className="mt-1 text-xs text-slate-400">
          Protected routes (<code className="text-slate-300">POST /triage</code>,{" "}
          <code className="text-slate-300">GET /stats</code>) enforce Cognito JWT verification at API Gateway and Lambda.
          Tokens stay in <code className="text-slate-300">sessionStorage</code> only.
        </p>

        {authPrompt && !isAuthenticated && (
          <div className="mt-3 rounded-xl border border-amber-400/35 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            {authPrompt}
          </div>
        )}

        {isAuthenticated && tokenMeta && (
          <div className="mt-3 grid grid-cols-1 gap-2 rounded-xl border border-emerald-400/20 bg-emerald-500/[0.05] p-3 text-[11px] text-slate-300 sm:grid-cols-3">
            <div>
              <span className="text-[10px] uppercase tracking-wider text-slate-500">Subject / Email</span>
              <p className="mt-0.5 truncate font-mono text-slate-100">{tokenMeta.email ?? tokenMeta.sub ?? "Active"}</p>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider text-slate-500">Tenant Scope</span>
              <p className="mt-0.5 truncate font-mono text-slate-100">{tokenMeta.tenantId ?? `user:${tokenMeta.sub ?? "scoped"}`}</p>
            </div>
            <div>
              <span className="text-[10px] uppercase tracking-wider text-slate-500">Expires</span>
              <p className="mt-0.5 font-mono text-slate-100">
                {tokenMeta.exp ? new Date(tokenMeta.exp * 1000).toLocaleTimeString() : "Session active"}
              </p>
            </div>
          </div>
        )}

        <div className="mt-4 flex gap-2">
          <button
            type="button"
            onClick={() => setAuthMode("cognito")}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              authMode === "cognito"
                ? "border border-cyan-400/40 bg-cyan-500/15 text-cyan-200"
                : "border border-white/10 bg-white/[0.03] text-slate-400 hover:text-slate-200"
            }`}
          >
            Sign In with Cognito
          </button>
          <button
            type="button"
            onClick={() => setAuthMode("token")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
              authMode === "token"
                ? "border border-cyan-400/40 bg-cyan-500/15 text-cyan-200"
                : "border border-white/10 bg-white/[0.03] text-slate-400 hover:text-slate-200"
            }`}
          >
            <KeyRound size={12} /> Paste Bearer JWT
          </button>
        </div>

        {authMode === "cognito" ? (
          <form onSubmit={(e) => void handleCognitoSubmit(e)} className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="grid gap-1">
              <span className="text-[11px] font-medium text-slate-400">Cognito App Client ID</span>
              <input
                value={clientId}
                onChange={(e) => setClientId(e.target.value)}
                placeholder="e.g. 5k8abc123def..."
                required
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 font-mono text-xs text-white outline-none focus:border-neon-cyan/50"
              />
            </label>
            <label className="grid gap-1">
              <span className="text-[11px] font-medium text-slate-400">AWS Region</span>
              <input
                value={region}
                onChange={(e) => setRegion(e.target.value)}
                placeholder="ap-southeast-2"
                required
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 font-mono text-xs text-white outline-none focus:border-neon-cyan/50"
              />
            </label>
            <label className="grid gap-1">
              <span className="text-[11px] font-medium text-slate-400">Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operator@example.com"
                required
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan/50"
              />
            </label>
            {challengeSession ? (
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-amber-300">New Permanent Password (12+ chars)</span>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  minLength={12}
                  required
                  className="rounded-xl border border-amber-400/40 bg-white/[0.04] px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan/50"
                />
              </label>
            ) : (
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-slate-400">Password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-white outline-none focus:border-neon-cyan/50"
                />
              </label>
            )}
            <div className="flex items-center gap-3 sm:col-span-2">
              <button
                type="submit"
                disabled={authLoading}
                data-hover="1"
                className="rounded-xl px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
                style={{ background: "linear-gradient(135deg,#7c5cfc,#06b6d4)" }}
              >
                {authLoading
                  ? "Signing in..."
                  : challengeSession
                    ? "Set Password & Sign In"
                    : "Sign In"}
              </button>
              {authError && <span className="text-xs text-rose-400">{authError}</span>}
              {authSuccess && <span className="text-xs text-emerald-300">{authSuccess}</span>}
            </div>
          </form>
        ) : (
          <form onSubmit={handleSaveManualToken} className="mt-3 grid gap-3">
            <label className="grid gap-1">
              <span className="text-[11px] font-medium text-slate-400">Cognito ID / Access JWT</span>
              <textarea
                rows={2}
                value={manualToken}
                onChange={(e) => setManualToken(e.target.value)}
                placeholder="eyJraWQiOi..."
                className="rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 font-mono text-[11px] text-white outline-none focus:border-neon-cyan/50"
              />
            </label>
            <div className="flex items-center gap-3">
              <button
                type="submit"
                data-hover="1"
                className="rounded-xl px-4 py-2 text-xs font-semibold text-white"
                style={{ background: "linear-gradient(135deg,#7c5cfc,#06b6d4)" }}
              >
                Save JWT to Session
              </button>
              {authError && <span className="text-xs text-rose-400">{authError}</span>}
              {authSuccess && <span className="text-xs text-emerald-300">{authSuccess}</span>}
            </div>
          </form>
        )}
      </div>

      <div className="card p-5">
        <div className="flex items-center gap-2 text-neon-cyan">
          <Globe size={16} />
          <h3 className="text-sm font-bold text-white">Deployed AWS Endpoints</h3>
        </div>
        <p className="mt-1 text-xs text-slate-400">
          Configured via <code className="text-slate-300">.env.local</code> in <code className="text-slate-300">ap-southeast-2</code>.
        </p>

        <div className="mt-4 space-y-3 text-xs">
          <div className="card2 p-3">
            <p className="text-[10px] uppercase tracking-wider text-slate-500">v1 · Single Heavy (Nova Pro)</p>
            <p className="mt-1 break-all font-mono text-slate-200">{v1Url ?? "Unconfigured"}</p>
          </div>
          <div className="card2 p-3">
            <p className="text-[10px] uppercase tracking-wider text-neon-cyan">v2 · Adaptive Router (Lite → Pro)</p>
            <p className="mt-1 break-all font-mono text-slate-200">{v2Url ?? "Unconfigured"}</p>
          </div>
        </div>
      </div>

      <div className="card flex flex-col justify-between p-5">
        <div>
          <div className="flex items-center gap-2 text-neon-purple">
            <Sliders size={16} />
            <h3 className="text-sm font-bold text-white">Quota Pacing & Reliability</h3>
          </div>
          <ul className="mt-3 space-y-2 text-xs text-slate-300">
            <li className="flex items-center gap-2">
              <Shield size={13} className="text-neon-green" />
              Concurrency capped at <strong>2 in-flight</strong> requests per stack
            </li>
            <li className="flex items-center gap-2">
              <Shield size={13} className="text-neon-green" />
              Pacing floor enforced at <strong>≥ 1,500 ms</strong> (~40 req/min safe margin)
            </li>
            <li className="flex items-center gap-2">
              <Shield size={13} className="text-neon-green" />
              Bedrock timeout budget: <strong>1+8s × 2 hops = 18s</strong> (&lt; 20s cap)
            </li>
          </ul>
        </div>

        <button
          onClick={onOpenCustom}
          data-hover="1"
          className="mt-4 flex items-center justify-center gap-2 rounded-xl py-2.5 text-xs font-semibold text-white"
          style={{ background: "linear-gradient(135deg,#7c5cfc,#00c2ff)" }}
        >
          <Terminal size={14} /> Open Single Ticket Tester
        </button>
      </div>
    </div>
  );
}
