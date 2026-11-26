export interface WarFinding {
  bp: string;
  title: string;
  before: string;
  after: string;
}

interface WarScorecardProps {
  findings: WarFinding[];
}

export default function WarScorecard({ findings }: WarScorecardProps) {
  return (
    <section className="glass flex flex-col gap-2 p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="kicker">Well-Architected audit flip</p>
          <p className="mt-0.5 text-[11px] text-slate-500">
            Sustainability + Cost Optimization · live framework corpus
          </p>
        </div>
        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 tnum">
          {findings.length} BPs
        </span>
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-1.5 overflow-y-auto">
        {findings.length === 0 ? (
          <p className="py-6 text-center text-[11px] text-slate-400">
            Baseline audit complete — v2 Best Practice flips populate after the router PR.
          </p>
        ) : (
          findings.map((finding) => (
            <div
              key={finding.bp}
              className="flex items-center gap-2 rounded-lg border border-slate-100 bg-white/60 px-2 py-1.5"
            >
              <span className="shrink-0 rounded-md bg-slate-900 px-1.5 py-0.5 font-mono text-[9px] font-semibold text-white">
                {finding.bp}
              </span>
              <span className="min-w-0 flex-1 truncate text-[11px] text-slate-600">{finding.title}</span>
              <span className="shrink-0 rounded-full border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[9px] font-medium text-rose-600">
                {finding.before}
              </span>
              <span className="shrink-0 text-slate-300">→</span>
              <span className="shrink-0 rounded-full border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-700">
                {finding.after}
              </span>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
