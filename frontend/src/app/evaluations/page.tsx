"use client";

import { useEffect, useState } from "react";
import { api, type EvaluationRun } from "@/lib/api";

// Dev-oriented evaluation dashboard (ADR 0010). Citation validity and warning
// counts are the deterministic trust floor; judge scores are semantic quality and
// are never the authority for citation validity (ADR 0010 / AC #5).
export default function EvaluationsPage() {
  const [runs, setRuns] = useState<EvaluationRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .listEvaluations()
      .then((items) => active && setRuns(items))
      .catch((err: Error) => active && setError(err.message));
    return () => {
      active = false;
    };
  }, []);

  async function runAll() {
    setRunning(true);
    setError(null);
    try {
      await api.runEvaluations();
      setRuns(await api.listEvaluations());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run evaluations");
    } finally {
      setRunning(false);
    }
  }

  // Show the latest run per scenario at the top.
  const latestByScenario = new Map<string, EvaluationRun>();
  for (const run of runs ?? []) {
    if (!latestByScenario.has(run.scenario_id)) {
      latestByScenario.set(run.scenario_id, run);
    }
  }
  const latest = [...latestByScenario.values()];

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <p className="label">Internal</p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Evaluations</h1>
          <p className="max-w-prose text-sm text-slate-600">
            Run scenario fixtures through the deterministic check floor and the
            LLM-as-judge rubric. Citation validity and warning counts are mechanical;
            judge scores measure semantic quality and never decide citations.
          </p>
        </div>
        <button type="button" className="button-primary" disabled={running} onClick={runAll}>
          {running ? "Running…" : "Run all evaluations"}
        </button>
      </header>

      {error && (
        <div className="card-padded border-rose-200 bg-rose-50/40">
          <p className="text-sm text-rose-600">{error}</p>
        </div>
      )}

      {runs && latest.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white/70 p-10 text-center">
          <h3 className="text-sm font-semibold text-slate-900">No evaluation runs yet</h3>
          <p className="mt-1 text-sm text-slate-600">
            Run the suite to score every scenario fixture against its ground truth.
          </p>
        </div>
      )}

      {latest.length > 0 && (
        <div className="grid gap-4">
          {latest.map((run) => (
            <EvaluationCard key={run.id} run={run} />
          ))}
        </div>
      )}
    </div>
  );
}

function EvaluationCard({ run }: { run: EvaluationRun }) {
  const citationsOk = run.citation_total > 0 && run.citation_verified === run.citation_total;
  const warnings = Object.entries(run.warning_code_counts);
  return (
    <section className="card-padded">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-slate-900">{run.scenario_title}</h2>
            <PassBadge passed={run.passed} />
          </div>
          <p className="mt-0.5 font-mono text-xs text-slate-500">{run.scenario_id}</p>
        </div>
        <div className="text-right text-xs text-slate-500">
          <p>{run.experiment_metadata.model_provider}</p>
          <p>{run.experiment_metadata.verifier_version}</p>
        </div>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-3">
        {/* Deterministic citation validity — the trust floor. */}
        <Metric label="Citation validity">
          <span className={citationsOk ? "text-emerald-700" : "text-rose-700"}>
            {run.citation_verified}/{run.citation_total} verified
          </span>
        </Metric>
        {/* Warning Code counts. */}
        <Metric label="Warnings">
          {warnings.length === 0 ? (
            <span className="text-slate-500">none</span>
          ) : (
            <span className="flex flex-wrap gap-1">
              {warnings.map(([code, count]) => (
                <span key={code} className="badge bg-amber-50 text-amber-700 ring-amber-200">
                  {code} ×{count}
                </span>
              ))}
            </span>
          )}
        </Metric>
        {/* Semantic judge scores (optional). */}
        <Metric label="Judge (semantic)">
          {run.judge_scores ? (
            <span className="text-slate-800">{run.judge_scores.overall.toFixed(2)} / 5 avg</span>
          ) : (
            <span className="text-slate-500">not scored (no model)</span>
          )}
        </Metric>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {run.checks.map((check) => (
          <span
            key={check.name}
            title={check.detail}
            className={`badge ring-1 ${
              check.passed
                ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                : "bg-rose-50 text-rose-700 ring-rose-200"
            }`}
          >
            {check.passed ? "✓" : "✗"} {check.name}
          </span>
        ))}
      </div>

      {run.judge_scores && (
        <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50/60 p-3">
          <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-600">
            {Object.entries(run.judge_scores.scores).map(([dim, score]) => (
              <span key={dim}>
                {dim.replace(/_/g, " ")}: <span className="font-semibold text-slate-900">{score}</span>
              </span>
            ))}
          </div>
          <p className="mt-2 text-xs italic text-slate-500">{run.judge_scores.rationale}</p>
        </div>
      )}
    </section>
  );
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <p className="label">{label}</p>
      <div className="mt-1 text-sm font-medium">{children}</div>
    </div>
  );
}

function PassBadge({ passed }: { passed: boolean }) {
  return passed ? (
    <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-200">passing</span>
  ) : (
    <span className="badge bg-rose-50 text-rose-700 ring-rose-200">failing</span>
  );
}
