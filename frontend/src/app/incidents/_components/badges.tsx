import type { IncidentStatus, Severity } from "@/lib/api";

export function SeverityBadge({ severity }: { severity: Severity | null }) {
  const map: Record<Severity, { color: string; dot: string }> = {
    sev0: { color: "bg-rose-50 text-rose-700 ring-rose-200", dot: "bg-rose-500" },
    sev1: { color: "bg-orange-50 text-orange-700 ring-orange-200", dot: "bg-orange-500" },
    sev2: { color: "bg-amber-50 text-amber-700 ring-amber-200", dot: "bg-amber-500" },
    sev3: { color: "bg-sky-50 text-sky-700 ring-sky-200", dot: "bg-sky-500" },
    sev4: { color: "bg-slate-50 text-slate-700 ring-slate-200", dot: "bg-slate-400" },
  };
  if (!severity) {
    return (
      <span className="badge bg-slate-50 text-slate-500 ring-slate-200">
        <span className="badge-dot bg-slate-300" />
        unspecified
      </span>
    );
  }
  const cfg = map[severity];
  return (
    <span className={`badge ${cfg.color}`}>
      <span className={`badge-dot ${cfg.dot}`} />
      {severity}
    </span>
  );
}

export function StatusBadge({ status }: { status: IncidentStatus }) {
  const map: Record<IncidentStatus, string> = {
    open: "bg-rose-50 text-rose-700 ring-rose-200",
    investigating: "bg-amber-50 text-amber-700 ring-amber-200",
    mitigated: "bg-sky-50 text-sky-700 ring-sky-200",
    resolved: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    closed: "bg-slate-100 text-slate-600 ring-slate-200",
  };
  return <span className={`badge ${map[status]}`}>{status}</span>;
}
