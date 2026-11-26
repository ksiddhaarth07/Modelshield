import { Globe, Shield, Sliders, Terminal } from "lucide-react";

interface SettingsPageProps {
  v1Url: string | null;
  v2Url: string | null;
  onOpenCustom: () => void;
}

export default function SettingsPage({ v1Url, v2Url, onOpenCustom }: SettingsPageProps) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
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
