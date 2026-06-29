"use client";

import { useEffect, useState } from "react";
import {
  api,
  type AnalysisMode,
  type EvaluationRun,
  type ScenarioSummary,
} from "@/lib/api";

// Dev-oriented evaluation dashboard (ADR 0010 / 0044). Each scenario runs under
// two configurations — the product "multi_pass" causal analysis and the
// "builder_only" baseline that skips the Falsification Round — so the value of
// bounded multi-pass reasoning is measured, not assumed (PRD #38). Citation
// validity and warning counts are the deterministic trust floor; judge scores are
// semantic quality and never decide citation validity (ADR 0010 / AC #5).
//
// Every scenario here is a bundled *demo fixture* run on offline replay: there is
// no live model call, so token usage is absent and "latency" is replay wall-clock
// noise, not a model-cost signal. The honest cost delta is the model-call count.
export default function EvaluationsPage() {
  const [runs, setRuns] = useState<EvaluationRun[] | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runningAll, setRunningAll] = useState(false);
  // The scenario id whose card is currently running, so only that card shows a
  // busy state instead of locking the whole page behind one global flag.
  const [runningScenario, setRunningScenario] = useState<string | null>(null);
  // Collapsed by default so the page opens as a short list, not a wall of detail.
  const [groupOpen, setGroupOpen] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  useEffect(() => {
    let active = true;
    Promise.all([api.listEvaluations(), api.listScenarios()])
      .then(([items, scns]) => {
        if (!active) return;
        setRuns(items);
        setScenarios(scns);
      })
      .catch((err: Error) => active && setError(err.message));
    return () => {
      active = false;
    };
  }, []);

  async function refresh() {
    setRuns(await api.listEvaluations());
  }

  async function runAll() {
    setRunningAll(true);
    setError(null);
    try {
      await api.runEvaluations();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run evaluations");
    } finally {
      setRunningAll(false);
    }
  }

  async function runScenario(scenarioId: string) {
    setRunningScenario(scenarioId);
    setError(null);
    try {
      await api.runEvaluations(scenarioId);
      await refresh();
      // Surface the result the user just asked for without making them hunt for it.
      setExpanded((prev) => new Set(prev).add(scenarioId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run evaluation");
    } finally {
      setRunningScenario(null);
    }
  }

  function toggleScenario(scenarioId: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(scenarioId)) next.delete(scenarioId);
      else next.add(scenarioId);
      return next;
    });
  }

  // Latest run per (scenario, configuration). Runs arrive newest-first, so the
  // first time we see a (scenario_id, analysis_mode) pair it is the latest.
  const latestByKey = new Map<string, EvaluationRun>();
  const titleById = new Map<string, string>();
  const order: string[] = [];
  // Seed order with the on-disk scenarios so every available demo fixture shows a
  // card — and a Run button — even before its first evaluation run.
  for (const scenario of scenarios ?? []) {
    order.push(scenario.id);
    titleById.set(scenario.id, scenario.title);
  }
  // Real-incident floor evaluations are a different shape (single configuration,
  // no judge); keep the latest per incident, newest-first, separate from the
  // scenario A/B comparison.
  const incidentEvals: EvaluationRun[] = [];
  const seenIncidents = new Set<string>();
  for (const run of runs ?? []) {
    if (run.evaluation_kind === "incident") {
      const key = run.incident_id ?? run.id;
      if (!seenIncidents.has(key)) {
        seenIncidents.add(key);
        incidentEvals.push(run);
      }
      continue;
    }
    const key = `${run.scenario_id}::${run.analysis_mode}`;
    if (!latestByKey.has(key)) latestByKey.set(key, run);
    if (!order.includes(run.scenario_id)) order.push(run.scenario_id);
    if (!titleById.has(run.scenario_id)) titleById.set(run.scenario_id, run.scenario_title);
  }
  const comparisons = order.map((scenarioId) => ({
    scenarioId,
    title: titleById.get(scenarioId) ?? scenarioId,
    multiPass: latestByKey.get(`${scenarioId}::multi_pass`) ?? null,
    builderOnly: latestByKey.get(`${scenarioId}::builder_only`) ?? null,
  }));

  const loading = runs === null || scenarios === null;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <p className="label">Internal · demo fixtures</p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Evaluations</h1>
          <p className="max-w-prose text-sm text-slate-600">
            Each bundled <span className="font-medium text-slate-700">demo scenario</span> is
            analyzed twice under matched constraints: the full{" "}
            <span className="font-medium text-indigo-700">multi-pass</span> causal analysis, and a{" "}
            <span className="font-medium text-slate-700">builder-only</span> baseline that skips the
            falsification round. Comparing them shows the falsification round earns its cost.
          </p>
        </div>
        <button type="button" className="button-primary" disabled={runningAll} onClick={runAll}>
          {runningAll ? "Running…" : "Run all evaluations"}
        </button>
      </header>

      {error && (
        <div className="card-padded border-rose-200 bg-rose-50/40">
          <p className="text-sm text-rose-600">{error}</p>
        </div>
      )}

      {loading && <p className="text-sm text-slate-500">Loading evaluations…</p>}

      {!loading && comparisons.length === 0 && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white/70 p-10 text-center">
          <h3 className="text-sm font-semibold text-slate-900">No demo scenarios available</h3>
          <p className="mt-1 text-sm text-slate-600">No scenario fixtures were found to evaluate.</p>
        </div>
      )}

      {comparisons.length > 0 && (
        <section className="card overflow-hidden">
          <button
            type="button"
            onClick={() => setGroupOpen((open) => !open)}
            className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition hover:bg-slate-50"
            aria-expanded={groupOpen}
          >
            <span className="flex items-center gap-2">
              <Chevron open={groupOpen} />
              <span className="text-sm font-semibold text-slate-900">Demo scenarios</span>
              <span className="badge bg-slate-100 text-slate-600 ring-slate-200">
                {comparisons.length}
              </span>
            </span>
            <span className="label">graded against ground truth · multi-pass vs baseline</span>
          </button>

          {groupOpen && (
            <div className="space-y-3 border-t border-slate-200 bg-slate-50/40 p-3">
              <Legend />
              {comparisons.map((comparison) => (
                <ComparisonCard
                  key={comparison.scenarioId}
                  {...comparison}
                  open={expanded.has(comparison.scenarioId)}
                  onToggle={() => toggleScenario(comparison.scenarioId)}
                  running={runningScenario === comparison.scenarioId}
                  disabled={runningAll || runningScenario !== null}
                  onRun={() => runScenario(comparison.scenarioId)}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {!loading && <IncidentEvaluations evals={incidentEvals} />}
    </div>
  );
}

// Aggregate review of real-incident floor evaluations (PRD: evaluate a real
// incident). These are triggered from each incident's analysis run and collected
// here. Unlike demo scenarios they have no ground truth — only the deterministic
// trust floor, never a judge — so the card is deliberately plainer and says so.
function IncidentEvaluations({ evals }: { evals: EvaluationRun[] }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="card overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition hover:bg-slate-50"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <Chevron open={open} />
          <span className="text-sm font-semibold text-slate-900">Your incidents</span>
          <span className="badge bg-slate-100 text-slate-600 ring-slate-200">{evals.length}</span>
        </span>
        <span className="label">deterministic floor only · no judge</span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-200 bg-slate-50/40 p-3">
          {evals.length === 0 ? (
            <p className="rounded-lg border border-dashed border-slate-300 bg-white/70 p-6 text-center text-sm text-slate-600">
              No incident evaluations yet. Open an incident with a succeeded analysis run and
              choose <span className="font-medium">Run evaluation</span> to grade it against the
              deterministic trust floor.
            </p>
          ) : (
            evals.map((run) => <IncidentEvalCard key={run.id} run={run} />)
          )}
        </div>
      )}
    </section>
  );
}

function IncidentEvalCard({ run }: { run: EvaluationRun }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold text-slate-900">{run.scenario_title}</h3>
            <span className="badge bg-sky-50 text-sky-700 ring-sky-200">Incident</span>
            <PassBadge passed={run.passed} />
          </div>
          <p className="mt-0.5 text-xs text-slate-500">
            Evaluated {new Date(run.created_at).toLocaleString()} · floor only (no ground truth)
          </p>
        </div>
        {run.incident_id && (
          <a
            href={`/incidents/${run.incident_id}`}
            className="inline-flex h-8 shrink-0 items-center rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50"
          >
            Open incident
          </a>
        )}
      </div>

      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <ChecksPanel run={run} />
        <div className="grid grid-cols-2 gap-3 self-start">
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
            <span className="text-slate-500" title="No ground-truth reference for a real incident, so the judge does not run.">
              n/a — no ground truth
            </span>
          </Metric>
        </div>
      </div>
    </section>
  );
}

// A compact, plain-language key so the two columns and the green/red checks read
// without prior knowledge of the harness.
function Legend() {
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-xs text-slate-600">
      <span className="inline-flex items-center gap-1.5">
        <span className="dot bg-indigo-500" /> multi-pass = the product
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="dot bg-slate-400" /> builder-only = baseline (no falsification)
      </span>
      <span>
        <span className="text-emerald-700">✓ checks</span> = deterministic trust floor
      </span>
      <span>
        <span className="font-medium">judge</span> = semantic quality only (never decides citations)
      </span>
    </div>
  );
}

function ComparisonCard({
  scenarioId,
  title,
  multiPass,
  builderOnly,
  open,
  onToggle,
  running,
  disabled,
  onRun,
}: {
  scenarioId: string;
  title: string;
  multiPass: EvaluationRun | null;
  builderOnly: EvaluationRun | null;
  open: boolean;
  onToggle: () => void;
  running: boolean;
  disabled: boolean;
  onRun: () => void;
}) {
  const meta = (multiPass ?? builderOnly)?.experiment_metadata;
  const everRun = multiPass !== null || builderOnly !== null;
  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 text-left"
        >
          <Chevron open={open} />
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2">
              <span className="truncate text-sm font-semibold text-slate-900">{title}</span>
              <span className="badge bg-amber-50 text-amber-700 ring-amber-200">Demo scenario</span>
            </span>
            <span className="mt-0.5 flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-slate-500">{scenarioId}</span>
              {everRun && (
                <>
                  <VerdictPill label="multi-pass" run={multiPass} />
                  <VerdictPill label="builder-only" run={builderOnly} />
                </>
              )}
            </span>
          </span>
        </button>
        <button
          type="button"
          className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white px-3 text-xs font-medium text-slate-700 shadow-sm transition hover:border-slate-300 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"
          disabled={disabled}
          onClick={onRun}
        >
          {running ? "Running…" : everRun ? "Re-run" : "Run"}
        </button>
      </div>

      {open && (
        <div className="border-t border-slate-200 p-4">
          {!everRun ? (
            <p className="text-sm text-slate-500">
              Not run yet. Use <span className="font-medium">Run</span> to evaluate this scenario.
            </p>
          ) : (
            <>
              <div className="grid gap-4 lg:grid-cols-2">
                <ConfigColumn label="Multi-pass causal analysis" mode="multi_pass" run={multiPass} />
                <ConfigColumn label="Builder-only baseline" mode="builder_only" run={builderOnly} />
              </div>
              {multiPass && builderOnly && (
                <DeltaRow multiPass={multiPass} builderOnly={builderOnly} />
              )}
              {meta && <Provenance meta={meta} multiPass={multiPass} builderOnly={builderOnly} />}
            </>
          )}
        </div>
      )}
    </section>
  );
}

// Collapsed-row verdict so the gist is visible without expanding the card.
function VerdictPill({ label, run }: { label: string; run: EvaluationRun | null }) {
  if (!run) {
    return (
      <span className="badge bg-slate-100 text-slate-500 ring-slate-200">{label}: not run</span>
    );
  }
  return run.passed ? (
    <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-200">{label}: passing</span>
  ) : (
    <span className="badge bg-rose-50 text-rose-700 ring-rose-200">{label}: failing</span>
  );
}

// The headline of the comparison: how much the falsification round changed the
// outcome. Model calls is the honest cost delta (deterministic); judge overall and
// failing-check count are the quality deltas.
function DeltaRow({
  multiPass,
  builderOnly,
}: {
  multiPass: EvaluationRun;
  builderOnly: EvaluationRun;
}) {
  const mpFailing = multiPass.checks.filter((c) => !c.passed).length;
  const boFailing = builderOnly.checks.filter((c) => !c.passed).length;
  const mpJudge = multiPass.judge_scores?.overall ?? null;
  const boJudge = builderOnly.judge_scores?.overall ?? null;
  const checkDelta = mpFailing - boFailing;
  // Fewer failing checks than baseline is good (green); more is bad; equal is neutral.
  const checkGood = checkDelta === 0 ? null : checkDelta < 0;
  return (
    <div className="mt-4 grid grid-cols-1 gap-3 rounded-xl border border-slate-200 bg-slate-50/60 p-3 sm:grid-cols-3">
      <DeltaCell
        label="Judge overall (multi-pass − baseline)"
        value={mpJudge !== null && boJudge !== null ? signed(mpJudge - boJudge, 2) : "—"}
        good={mpJudge !== null && boJudge !== null ? mpJudge - boJudge >= 0 : null}
      />
      <DeltaCell
        label="Failing checks (multi-pass − baseline)"
        value={signed(checkDelta, 0)}
        good={checkGood}
      />
      <DeltaCell
        label="Model calls (cost of the extra passes)"
        value={signed(multiPass.model_calls - builderOnly.model_calls, 0)}
        good={null}
      />
    </div>
  );
}

function DeltaCell({
  label,
  value,
  good,
}: {
  label: string;
  value: string;
  good: boolean | null;
}) {
  const tone = good === null ? "text-slate-900" : good ? "text-emerald-700" : "text-rose-700";
  return (
    <div className="text-center">
      <p className={`text-lg font-semibold ${tone}`}>{value}</p>
      <p className="label normal-case tracking-normal">{label}</p>
    </div>
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
    mode === "multi_pass" ? "border-indigo-200 bg-indigo-50/40" : "border-slate-200 bg-slate-50/60";
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
          <ChecksPanel run={run} />

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
                <span className="text-slate-500">not scored (no model)</span>
              )}
            </Metric>
          </div>

          {/* Judge breakdown is opt-in so it does not crowd the headline metrics. */}
          {run.judge_scores && <JudgeBreakdown scores={run.judge_scores} />}

          <WarningCodes counts={run.warning_code_counts} />

          {/* Cost: better reasoning should not be bought with unbounded cost. Model
              calls is the honest deterministic signal; tokens are absent on offline
              replay and replay latency is wall-clock noise, both labeled as such. */}
          <div className="grid grid-cols-3 gap-2 border-t border-slate-200 pt-3 text-center">
            <Cost label="Model calls" value={run.model_calls} emphasis />
            <Cost
              label="Tokens"
              value={run.total_tokens > 0 ? run.total_tokens : "n/a"}
              title={
                run.total_tokens > 0
                  ? undefined
                  : "No tokens recorded: demo scenarios run on offline replay with no live model call."
              }
            />
            <Cost
              label="Replay latency"
              value={`${run.latency_ms} ms`}
              title="Wall-clock time of the offline replay, not a model-cost signal. It varies run to run and is not comparable across configurations."
            />
          </div>
        </div>
      )}
    </div>
  );
}

// Deterministic checks are the trust floor but there are many of them, so they are
// summarized to a pass count by default and explained on demand behind an info
// toggle — each check named, described, and shown with this run's outcome.
function ChecksPanel({ run }: { run: EvaluationRun }) {
  const [open, setOpen] = useState(false);
  const total = run.checks.length;
  const passed = run.checks.filter((c) => c.passed).length;
  const allPass = passed === total;
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <span className="label">Deterministic checks</span>
        <div className="flex items-center gap-2">
          <span className={allPass ? "text-xs text-emerald-700" : "text-xs text-rose-700"}>
            {passed}/{total} passing
          </span>
          <button
            type="button"
            onClick={() => setOpen((o) => !o)}
            aria-expanded={open}
            aria-label="Explain checks"
            title="What do these checks mean?"
            className="inline-flex h-5 w-5 items-center justify-center rounded-full border border-slate-300 text-[11px] font-semibold text-slate-500 transition hover:border-slate-400 hover:text-slate-700"
          >
            i
          </button>
        </div>
      </div>

      {/* When all pass and the panel is closed, stay quiet. Surface failing checks
          compactly even while closed, since a failure is the reason to look. */}
      {!open && !allPass && (
        <ul className="mt-2 space-y-1">
          {run.checks
            .filter((c) => !c.passed)
            .map((check) => (
              <li key={check.name} className="text-xs text-rose-600">
                <span className="font-medium">✗ {check.name}:</span> {check.detail}
              </li>
            ))}
        </ul>
      )}

      {open && (
        <ul className="mt-2 space-y-2 rounded-lg border border-slate-200 bg-white p-3">
          {run.checks.map((check) => (
            <li key={check.name} className="text-xs">
              <div className="flex items-baseline gap-1.5">
                <span className={check.passed ? "text-emerald-600" : "text-rose-600"}>
                  {check.passed ? "✓" : "✗"}
                </span>
                <span className="font-mono font-medium text-slate-800">{check.name}</span>
              </div>
              <p className="mt-0.5 pl-5 text-slate-500">{CHECK_INFO[check.name] ?? check.detail}</p>
              <p className="pl-5 text-slate-400">
                This run: <span className="text-slate-600">{check.detail}</span>
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// Plain-language descriptions of each deterministic check (kept in step with the
// backend check functions in backend/postmortem/evaluation.py).
const CHECK_INFO: Record<string, string> = {
  citation_integrity:
    "Every cited evidence reference resolves to its exact source lines. The mechanical citation-validity floor — the judge is never consulted for it.",
  required_outputs: "The postmortem carries its required sections: a summary, a timeline, and hypotheses.",
  timeline_ordering: "Dated timeline events are in chronological order.",
  hypothesis_multiplicity:
    "Ambiguous evidence yields multiple competing hypotheses instead of collapsing to a single apparent answer.",
  insufficient_evidence_refusal:
    "The system refuses (no confident postmortem) exactly when evidence is insufficient — and does not wrongly reject good evidence.",
  advisory_ranking_coverage:
    "Every hypothesis holds a distinct advisory rank forming a complete 1..N ordering.",
  causal_challenge_coverage:
    "Every hypothesis carries a falsification challenge. This is the headline multi-pass-vs-baseline signal: the baseline skips the falsification round, so it fails here.",
  alternative_consideration:
    "Each declared plausible alternative cause was generated as a hypothesis and ranked below the lead — considered and rejected, not ignored.",
  counterevidence_coverage:
    "The falsifier surfaced every known counterevidence item the scenario declares, cited to exact evidence lines.",
  unsupported_causal_claims:
    "The top-ranked hypothesis rests on evidence that actually supports it; an unsupported leader fails.",
  causal_refusal: "The run refuses exactly when the scenario's expectations say it should.",
  causal_role_constraints:
    "A non-refusal run produces at least one finalizable (supported/partial) failure-mechanism candidate; a refusal run produces none.",
  unacceptable_overclaims:
    "The narrative contains none of the scenario's declared 'unacceptable overclaim' phrases — penalizes confident-but-shallow output.",
};

// The six rubric dimensions in their canonical order (ADR 0044), each 1-5.
const JUDGE_DIMENSIONS: ReadonlyArray<{ key: string; label: string }> = [
  { key: "timeline_accuracy", label: "Timeline accuracy" },
  { key: "root_cause_quality", label: "Root-cause quality" },
  { key: "evidence_grounding", label: "Evidence grounding" },
  { key: "uncertainty_honesty", label: "Uncertainty honesty" },
  { key: "explanatory_coverage", label: "Explanatory coverage" },
  { key: "falsification_quality", label: "Falsification quality" },
];

function JudgeBreakdown({
  scores,
}: {
  scores: { scores: Record<string, number>; rationale: string };
}) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-xs font-medium text-slate-500 transition hover:text-slate-700"
      >
        <Chevron open={open} />
        Judge breakdown
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-600">
            {JUDGE_DIMENSIONS.map(({ key, label }) => {
              const score = scores.scores[key];
              if (score === undefined) return null;
              return (
                <div key={key} className="flex items-center justify-between gap-2">
                  <span>{label}</span>
                  <span className="font-semibold text-slate-900">{score}/5</span>
                </div>
              );
            })}
          </div>
          {scores.rationale && (
            <p className="text-xs italic leading-relaxed text-slate-600">“{scores.rationale}”</p>
          )}
        </div>
      )}
    </div>
  );
}

function WarningCodes({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  if (entries.length === 0) return null;
  return (
    <div>
      <p className="label">Warnings</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {entries.map(([code, count]) => (
          <span key={code} className="badge bg-amber-50 text-amber-700 ring-amber-200">
            {code}
            {count > 1 ? ` ×${count}` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

// Component versions and the model/retrieval configuration the run executed under
// (ADR 0025 experiment metadata), collapsed by default so provenance is auditable
// without crowding the comparison.
function Provenance({
  meta,
  multiPass,
  builderOnly,
}: {
  meta: EvaluationRun["experiment_metadata"];
  multiPass: EvaluationRun | null;
  builderOnly: EvaluationRun | null;
}) {
  const ref = multiPass ?? builderOnly;
  const rows: Array<[string, string | null]> = [
    ["Model provider", meta.model_provider],
    ["Retrieval strategy", meta.retrieval_strategy],
    ["Chunking strategy", meta.chunking_strategy],
    ["Pipeline version", meta.pipeline_version],
    ["Prompt version", meta.prompt_version],
    ["Verifier version", meta.verifier_version],
    ["Check suite version", ref?.check_suite_version ?? null],
    ["Judge version", ref?.judge_version ?? "—"],
    ["Last run", ref ? new Date(ref.created_at).toLocaleString() : null],
  ];
  return (
    <details className="mt-4 text-xs text-slate-600">
      <summary className="cursor-pointer select-none font-medium text-slate-500 hover:text-slate-700">
        Provenance
      </summary>
      <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
        {rows.map(([k, v]) =>
          v ? (
            <div key={k} className="flex justify-between gap-3">
              <dt className="text-slate-500">{k}</dt>
              <dd className="font-mono text-slate-700">{v}</dd>
            </div>
          ) : null,
        )}
      </dl>
    </details>
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

function Cost({
  label,
  value,
  emphasis,
  title,
}: {
  label: string;
  value: number | string;
  emphasis?: boolean;
  title?: string;
}) {
  return (
    <div title={title} className={title ? "cursor-help" : undefined}>
      <p className={`text-sm font-semibold ${emphasis ? "text-slate-900" : "text-slate-500"}`}>
        {value}
      </p>
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

// A small rotating disclosure chevron shared by every collapsible affordance.
function Chevron({ open }: { open: boolean }) {
  return (
    <span
      aria-hidden
      className={`inline-block text-slate-400 transition-transform ${open ? "rotate-90" : ""}`}
    >
      ▸
    </span>
  );
}

// Format a delta with an explicit sign so "better/worse than baseline" is unambiguous.
function signed(value: number, digits: number): string {
  const fixed = value.toFixed(digits);
  return value > 0 ? `+${fixed}` : fixed;
}
