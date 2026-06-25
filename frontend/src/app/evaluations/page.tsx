"use client";

import { useEffect, useState } from "react";
import { api, type AnalysisMode, type EvaluationRun } from "@/lib/api";

// Dev-oriented evaluation dashboard (ADR 0010 / 0044). Each scenario runs under
// two configurations — the product "multi_pass" causal analysis and the
// "builder_only" baseline that skips the Falsification Round — so the value of
// bounded multi-pass reasoning is measured, not assumed (PRD #38). Citation
// validity and warning counts are the deterministic trust floor; judge scores are
// semantic quality and never decide citation validity (ADR 0010 / AC #5).
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

  // Latest run per (scenario, configuration). Runs arrive newest-first, so the
  // first time we see a (scenario_id, analysis_mode) pair it is the latest.
  const latestByKey = new Map<string, EvaluationRun>();
  const scenarioOrder: string[] = [];
  for (const run of runs ?? []) {
    const key = `${run.scenario_id}::${run.analysis_mode}`;
    if (!latestByKey.has(key)) latestByKey.set(key, run);
    if (!scenarioOrder.includes(run.scenario_id)) scenarioOrder.push(run.scenario_id);
  }
  const comparisons = scenarioOrder.map((scenarioId) => ({
    scenarioId,
    multiPass: latestByKey.get(`${scenarioId}::multi_pass`) ?? null,
    builderOnly: latestByKey.get(`${scenarioId}::builder_only`) ?? null,
  }));

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <p className="label">Internal</p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Evaluations</h1>
          <p className="max-w-prose text-sm text-slate-600">
            Each scenario runs through bounded multi-pass causal analysis and a
            builder-only baseline under matched model and retrieval constraints.
            Deterministic checks are the trust floor; judge scores measure semantic
            quality and never decide citations. Calls, tokens, and latency show that
            better reasoning is not bought with unbounded cost.
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

      {runs && comparisons.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white/70 p-10 text-center">
          <h3 className="text-sm font-semibold text-slate-900">No evaluation runs yet</h3>
          <p className="mt-1 text-sm text-slate-600">
            Run the suite to score every scenario fixture under both configurations.
          </p>
        </div>
      )}

      {comparisons.length > 0 && (
        <div className="grid gap-4">
          {comparisons.map((comparison) => (
            <ComparisonCard key={comparison.scenarioId} {...comparison} />
          ))}
        </div>
      )}
    </div>
  );
}

function ComparisonCard({
  scenarioId,
  multiPass,
  builderOnly,
}: {
  scenarioId: string;
  multiPass: EvaluationRun | null;
  builderOnly: EvaluationRun | null;
}) {
  const title = (multiPass ?? builderOnly)?.scenario_title ?? scenarioId;
  const meta = (multiPass ?? builderOnly)?.experiment_metadata;
  return (
    <section className="card-padded">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-slate-900">{title}</h2>
          <p className="mt-0.5 font-mono text-xs text-slate-500">{scenarioId}</p>
        </div>
        {meta && (
          <div className="text-right text-xs text-slate-500">
            <p>{meta.model_provider}</p>
            <p>{meta.verifier_version}</p>
          </div>
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <ConfigColumn label="Multi-pass causal analysis" mode="multi_pass" run={multiPass} />
        <ConfigColumn label="Builder-only baseline" mode="builder_only" run={builderOnly} />
      </div>
    </section>
  );
}

function ConfigColumn({
  label,
  mode,
  run,
}: {
  label: string;
  mode: AnalysisMode;
  run: EvaluationRun | null;
}) {
  const accent =
    mode === "multi_pass"
      ? "border-indigo-200 bg-indigo-50/40"
      : "border-slate-200 bg-slate-50/60";
  return (
    <div className={`rounded-xl border ${accent} p-4`}>
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">{label}</h3>
        {run ? <PassBadge passed={run.passed} /> : null}
      </div>

      {!run ? (
        <p className="mt-3 text-sm text-slate-500">Not run yet.</p>
      ) : (
        <div className="mt-3 space-y-4">
          <ChecksSummary run={run} />

          <div className="grid grid-cols-2 gap-3">
            <Metric label="Citation validity">
              <span
                className={
                  run.citation_total > 0 && run.citation_verified === run.citation_total
                    ? "text-emerald-700"
                    : run.citation_total === 0
                      ? "text-slate-500"
                      : "text-rose-700"
                }
              >
                {run.citation_verified}/{run.citation_total} verified
              </span>
            </Metric>
            <Metric label="Judge (semantic)">
              {run.judge_scores ? (
                <span className="text-slate-800">{run.judge_scores.overall.toFixed(2)} / 5</span>
              ) : (
                <span className="text-slate-500">not scored</span>
              )}
            </Metric>
          </div>

          {/* Causal-depth judge dimensions, the point of the comparison (PRD #38). */}
          {run.judge_scores && (
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
              <JudgeDim scores={run.judge_scores.scores} dim="explanatory_coverage" />
              <JudgeDim scores={run.judge_scores.scores} dim="falsification_quality" />
            </div>
          )}

          {/* Cost: better reasoning should not be bought with unbounded cost. */}
          <div className="grid grid-cols-3 gap-2 border-t border-slate-200 pt-3 text-center">
            <Cost label="Model calls" value={run.model_calls} />
            <Cost label="Tokens" value={run.total_tokens} />
            <Cost label="Latency" value={`${run.latency_ms} ms`} />
          </div>
        </div>
      )}
    </div>
  );
}

function ChecksSummary({ run }: { run: EvaluationRun }) {
  const total = run.checks.length;
  const passed = run.checks.filter((c) => c.passed).length;
  const failing = run.checks.filter((c) => !c.passed);
  return (
    <div>
      <div className="flex items-center justify-between text-xs">
        <span className="label">Deterministic checks</span>
        <span className={passed === total ? "text-emerald-700" : "text-rose-700"}>
          {passed}/{total} passing
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
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
      {failing.length > 0 && (
        <p className="mt-2 text-xs italic text-rose-600">{failing[0].detail}</p>
      )}
    </div>
  );
}

function JudgeDim({
  scores,
  dim,
}: {
  scores: Record<string, number>;
  dim: string;
}) {
  const score = scores[dim];
  if (score === undefined) return null;
  return (
    <span>
      {dim.replace(/_/g, " ")}: <span className="font-semibold text-slate-900">{score}/5</span>
    </span>
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

function Cost({ label, value }: { label: string; value: number | string }) {
  return (
    <div>
      <p className="text-sm font-semibold text-slate-900">{value}</p>
      <p className="label">{label}</p>
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
