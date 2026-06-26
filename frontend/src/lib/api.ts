// Typed client for the Postmortem backend.
//
// The web UI and the future CLI share the backend service layer (ADR 0004);
// this module is the browser's thin transport over the same resource and
// command endpoints. Auth is the single-user bearer-token gate (ADR 0017).

export type Severity = "sev0" | "sev1" | "sev2" | "sev3" | "sev4";

export type IncidentStatus =
  | "open"
  | "investigating"
  | "mitigated"
  | "resolved"
  | "closed";

export type ArtifactSourceType =
  | "incident_notes"
  | "logs"
  | "stack_trace"
  | "deployment_notes"
  | "other";

export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export type RunStage =
  | "normalizing_evidence"
  | "extracting_incident_facts"
  | "analyzing_causal_hypotheses"
  | "verifying_citations"
  | "drafting_postmortem"
  | "flagging_unsupported_claims";

export type StageStatus = "running" | "succeeded" | "failed";

// The six MVP stages in order, with status-page labels (ADR 0026 / 0005). The
// UI renders all six up front so the pipeline is legible even before a run has
// produced an event for a later stage.
export const RUN_STAGES: ReadonlyArray<{ stage: RunStage; label: string }> = [
  { stage: "normalizing_evidence", label: "Normalizing evidence" },
  { stage: "extracting_incident_facts", label: "Extracting incident facts" },
  { stage: "analyzing_causal_hypotheses", label: "Analyzing causal hypotheses" },
  { stage: "verifying_citations", label: "Verifying citations" },
  { stage: "drafting_postmortem", label: "Drafting postmortem" },
  { stage: "flagging_unsupported_claims", label: "Flagging unsupported claims" },
];

export interface Incident {
  id: string;
  workspace_id: string;
  title: string;
  summary: string | null;
  severity: Severity | null;
  status: IncidentStatus;
  started_at: string | null;
  detected_at: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArtifactLine {
  number: number;
  text: string;
}

export interface Artifact {
  id: string;
  incident_id: string;
  source_type: ArtifactSourceType;
  source_name: string;
  body: string;
  line_count: number;
  included_in_analysis_run: boolean;
  created_at: string;
  updated_at: string;
  lines: ArtifactLine[];
}

export interface ExperimentMetadata {
  pipeline_version: string;
  prompt_version: string;
  model_provider: string;
  retrieval_strategy: string;
  chunking_strategy: string;
  verifier_version: string;
  // The recorded Reasoning Budget the Causal Analysis Stage ran under (ADR 0043):
  // per-role and stage limits for retrieval, tokens, and calls. Null on older runs.
  reasoning_budget: Record<string, number | string> | null;
}

export interface RunStageEvent {
  id: string;
  sequence: number;
  stage: RunStage;
  status: StageStatus;
  attempt: number;
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  usage: Record<string, unknown> | null;
  warning_codes: string[];
  error: string | null;
}

export interface AnalysisRun {
  id: string;
  incident_id: string;
  status: RunStatus;
  error: string | null;
  // Controlled Causal Analysis Stage failure diagnostics (ADR 0043): a
  // machine-readable code and the failed role/invocation, set only when stage 3
  // fails through an exhausted Targeted Repair or Reasoning Budget.
  failure_code: string | null;
  failed_substep: string | null;
  experiment_metadata: ExperimentMetadata;
  artifact_ids: string[];
  stage_events: RunStageEvent[];
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export function isTerminalRunStatus(status: RunStatus): boolean {
  return status === "succeeded" || status === "failed";
}

// Deterministic citation-integrity outcome stamped by the verifying_citations
// stage (ADR 0014). `unverified` is the pre-verification default; the rest mirror
// the backend CitationIntegrityStatus.
export type CitationVerifierStatus =
  | "unverified"
  | "verified"
  | "artifact_missing"
  | "line_range_invalid"
  | "snippet_mismatch";

export interface EvidenceRef {
  id: string;
  artifact_id: string;
  source_name: string;
  line_start: number;
  line_end: number;
  snippet: string;
  confidence_score: number;
  verifier_status: CitationVerifierStatus;
}

export type HypothesisReviewStatus = "proposed" | "accepted" | "rejected";

// Semantic claim-support judgment on each Major Claim (ADR 0014). `unevaluated`
// is the pre-flagging default; the rest are the verifier's verdict.
export type ClaimSupportStatus =
  | "unevaluated"
  | "supported"
  | "partial"
  | "unsupported";

export interface ImpactClaim {
  id: string;
  sequence: number;
  description: string;
  assumption: boolean;
  support_status: ClaimSupportStatus;
  support_rationale: string | null;
  evidence_refs: EvidenceRef[];
}

// The review lifecycle of a generated Remediation Proposal (ADR 0041): the
// generated default "proposed", then a human disposition. An accepted proposal
// links to a Causal Factor or Evidence Gap; the others carry none.
export type RemediationStatus = "proposed" | "accepted" | "rejected" | "deferred";

export type RemediationLinkKind = "causal_factor" | "evidence_gap";

// The Causal Factor or Evidence Gap an accepted proposal points at (ADR 0041),
// resolved for display. `label` is a ready-to-render summary of the target.
export interface RemediationLink {
  kind: RemediationLinkKind;
  label: string;
  causal_factor_id: string | null;
  causal_factor_role: string | null;
  hypothesis_id: string | null;
  hypothesis_title: string | null;
  evidence_gap_challenge_id: string | null;
  evidence_gap_index: number | null;
  evidence_gap_text: string | null;
}

// A generated Remediation Proposal with its human decision overlay (ADR 0041).
// The generated `description` and `evidence_refs` are immutable (ADR 0016); the
// decision overlay records the human's disposition. `link` is present only on an
// accepted proposal and points at why the work matters (PRD story 53).
export interface ActionItem {
  id: string;
  sequence: number;
  description: string;
  evidence_refs: EvidenceRef[];
  review_status: RemediationStatus;
  decision_rationale: string | null;
  decided_by: string | null;
  decided_by_display: string | null;
  decided_at: string | null;
  link: RemediationLink | null;
}

// The link an accepted proposal must supply: exactly one target (ADR 0041).
export interface RemediationLinkInput {
  kind: RemediationLinkKind;
  causal_factor_id?: string;
  evidence_gap_challenge_id?: string;
  evidence_gap_index?: number;
}

// Command payload to accept, reject, or defer a Remediation Proposal (ADR 0041).
export interface RemediationDecisionInput {
  decision: RemediationStatus;
  rationale?: string;
  link?: RemediationLinkInput;
}

export interface ReviewerNote {
  id: string;
  run_id: string;
  hypothesis_id: string | null;
  body: string;
  created_at: string;
}

// Challenge Severity advises causal-role suitability (ADR 0034): critical blocks
// use as the failure mechanism, material limits the causal role, minor qualifies.
export type ChallengeSeverity = "critical" | "material" | "minor";

// A factual statement in a Hypothesis Challenge that weakens it (ADR 0034). A
// Major Claim: cited EvidenceRefs or an explicit assumption marker.
export interface Counterclaim {
  id: string;
  sequence: number;
  statement: string;
  assumption: boolean;
  evidence_refs: EvidenceRef[];
}

// The bounded falsifier's challenge of one RCA Hypothesis (ADR 0034). Surfaces
// the challenge's structured output — never hidden reasoning or chat history.
export interface HypothesisChallenge {
  id: string;
  challenged_claim: string;
  severity: ChallengeSeverity;
  counterclaims: Counterclaim[];
  evidence_gaps: string[];
  falsification_tests: string[];
}

// Per-dimension explanation of a hypothesis's advisory rank (ADR 0037). The five
// assessment dimensions plus a one-line summary; ordering is explained through
// these, never as a probability.
export interface RankingRationale {
  support_strength: string;
  counterevidence_severity: string;
  explanatory_coverage: string;
  evidence_gaps: string;
  assumption_dependence: string;
  summary: string;
}

export interface Hypothesis {
  id: string;
  run_id: string;
  // Original builder/generation order, retained for audit (ADR 0037).
  rank: number;
  // Post-challenge Advisory Hypothesis Ranking position; drives display order.
  // Null only before the ranking substep runs (or on an older run).
  advisory_rank: number | null;
  ranking_rationale: RankingRationale | null;
  // The advisory leader carries this when its challenge is critical, so the rank
  // is never mistaken for confidence (PRD #26 user stories 21-22).
  leading_but_critically_challenged: boolean;
  // Provenance within the Causal Analysis Stage (ADR 0036): "initial" for a
  // builder hypothesis, "proposed" for a falsifier-introduced missed alternative
  // from the bounded expansion round. The Review Surface distinguishes the two
  // without treating either as a Root Cause Conclusion (PRD #30).
  origin: "initial" | "proposed";
  title: string;
  summary: string;
  assumption: boolean;
  review_status: HypothesisReviewStatus;
  support_status: ClaimSupportStatus;
  support_rationale: string | null;
  unknowns: string[];
  validation_steps: string[];
  supporting_evidence: EvidenceRef[];
  contradicting_evidence: EvidenceRef[];
  action_items: ActionItem[];
  reviewer_notes: ReviewerNote[];
  // The bounded falsifier's challenge, present on every hypothesis in a
  // successful run (ADR 0034).
  challenge: HypothesisChallenge | null;
}

export interface TimelineEvent {
  id: string;
  sequence: number;
  normalized_ts: string | null;
  original_ts_text: string | null;
  uncertain: boolean;
  description: string;
  evidence_refs: EvidenceRef[];
}

// The structured Postmortem composed by the drafting stage (ADR 0012). The
// summary and lessons come from the Postmortem itself; timeline, run-level
// impact, and hypotheses (with nested remediation) are composed from the run's
// structured rows. Impact is a run-level incident fact shown once, independent
// of hypothesis count (ADR 0033).
export interface Postmortem {
  id: string;
  run_id: string;
  incident_title: string;
  incident_severity: string | null;
  summary: string;
  lessons_learned: string[];
  // Refusal assessment (ADR 0032 / 0015): on "insufficient" the Review Surface
  // withholds a confident root cause and shows what is missing / what to collect.
  evidence_sufficiency: "sufficient" | "insufficient";
  evidence_gaps: string[];
  next_validation_steps: string[];
  // Lifecycle state (ADR 0035 / 0039 / 0040 / 0045, PRD #26): an automated run is
  // "provisional" until a human finalizes a Root Cause Conclusion, then
  // "finalized". "disputed" is derived: a finalized conclusion carrying an open
  // Conclusion Discrepancy is no longer authoritative and review is unresolved.
  // "superseded" is derived: this run's conclusion has been replaced by a
  // Superseding Conclusion, so authority moved to the successor.
  conclusion_status: "provisional" | "finalized" | "disputed" | "superseded";
  composer_version: string;
  timeline: TimelineEvent[];
  impact_claims: ImpactClaim[];
  hypotheses: Hypothesis[];
  // The finalized human Root Cause Conclusion (ADR 0039), present only once a
  // reviewer finalizes one; null while the draft is provisional.
  conclusion: RootCauseConclusion | null;
  created_at: string;
}

// The causal role a Causal Factor plays in a finalized Root Cause Conclusion
// (ADR 0039). Exactly one failure_mechanism; triggers/amplifying are optional and
// repeatable.
export type CausalRole = "failure_mechanism" | "trigger" | "amplifying_condition";

// A Causal Factor: an accepted hypothesis the reviewer assigned a causal role
// (ADR 0039). Carries the hypothesis provenance and its verified supporting
// citations so the conclusion is navigable to exact evidence.
export interface CausalFactor {
  id: string;
  role: CausalRole;
  hypothesis_id: string;
  title: string;
  summary: string;
  support_status: ClaimSupportStatus;
  advisory_rank: number | null;
  supporting_evidence: EvidenceRef[];
  // Reviewer qualifications preserved wherever the factor renders (ADR 0042, PRD
  // #26 stories 38-41). A partially supported factor carries a Partial-Support
  // Acknowledgment; a critically challenged failure mechanism carries a
  // Critical-Challenge Override. `challenge` is the factor hypothesis's full
  // persisted Hypothesis Challenge so the actual critical challenge stays visible
  // and the override can be audited against the concern it addresses (story 41).
  partial_support_acknowledgment: string | null;
  critical_challenge_override: string | null;
  challenge: HypothesisChallenge | null;
}

// A labeled, unevidenced reviewer belief recorded with a conclusion (ADR 0042).
// Stored separately from the evidence-backed Causal Factors and always rendered as
// an explicit assumption, never as established fact (PRD #26 story 38).
export interface HumanAssumption {
  id: string;
  statement: string;
  created_at: string;
}

// An append-only flag disputing a Root Cause Conclusion (ADR 0040). An open
// discrepancy makes the conclusion a Disputed Conclusion — preserved for audit,
// but no longer authoritative, with review returned to unresolved.
export interface ConclusionDiscrepancy {
  id: string;
  conclusion_id: string;
  run_id: string;
  explanation: string;
  raised_by: string;
  raised_by_display: string | null;
  created_at: string;
}

// A summary-level link to another conclusion in a supersession chain (ADR 0045):
// the disputed predecessor a conclusion replaced, the successor that replaced it,
// or an entry in the predecessor `history`. Summary-level so the chain renders
// without unbounded nesting, while preserving provenance and discrepancies.
export interface SupersededLink {
  id: string;
  run_id: string;
  incident_id: string;
  summary: string;
  finalized_by: string;
  finalized_by_display: string | null;
  finalized_at: string;
  disputed: boolean;
  discrepancies: ConclusionDiscrepancy[];
}

// The finalized human Root Cause Conclusion (ADR 0039). Distinct from the
// Advisory Hypothesis Ranking: a ranking recommends candidates, this is the
// human's decision. Immutable, with Conclusion Provenance. `disputed` is true
// once an append-only Conclusion Discrepancy has been raised against it (ADR 0040).
export interface RootCauseConclusion {
  id: string;
  run_id: string;
  incident_id: string;
  summary: string;
  finalized_by: string;
  finalized_by_display: string | null;
  finalized_at: string;
  failure_mechanism: CausalFactor;
  triggers: CausalFactor[];
  amplifying_conditions: CausalFactor[];
  // Unevidenced reviewer beliefs, recorded separately from the factors (ADR 0042).
  human_assumptions: HumanAssumption[];
  disputed: boolean;
  discrepancies: ConclusionDiscrepancy[];
  // Superseding-chain links (ADR 0045): the disputed predecessor this conclusion
  // replaced, the successor that replaced it (null at the authoritative tail), the
  // full predecessor chain oldest-first for audit, and whether this conclusion is
  // the undisputed, un-superseded tail.
  supersedes: SupersededLink | null;
  superseded_by: SupersededLink | null;
  history: SupersededLink[];
  authoritative: boolean;
  created_at: string;
}

// One factor the reviewer assigns when finalizing (ADR 0039 / 0042). A partially
// supported factor must carry an acknowledgment; a critically challenged failure
// mechanism must carry an override (the backend enforces when each is required).
export interface CausalFactorInput {
  hypothesis_id: string;
  role: CausalRole;
  partial_support_acknowledgment?: string;
  critical_challenge_override?: string;
}

// How a Markdown export treats unsupported/assumption claims (ADR 0015): a clean
// export omits them; an audit export retains them, labeled, for review.
export type ExportMode = "clean" | "audit";

export interface MarkdownExport {
  run_id: string;
  mode: ExportMode;
  filename: string;
  markdown: string;
}

// A file-based Incident Scenario the demo operator can seed (ADR 0006 / 0007).
export interface ScenarioSummary {
  id: string;
  title: string;
  severity: Severity | null;
  summary: string | null;
  ambiguity_notes: string | null;
  evaluation_tags: string[];
  expected_hypothesis_families: string[];
  evidence_count: number;
}

// Result of seeding a scenario: the created incident and its started run.
export interface ScenarioSeedResult {
  scenario_id: string;
  incident_id: string;
  run_id: string;
  run_status: RunStatus;
}

// One deterministic check outcome in an Evaluation Run (ADR 0010 trust floor).
export interface EvaluationCheck {
  name: string;
  passed: boolean;
  detail: string;
}

// Semantic judge rubric scores. Never the citation-validity authority (ADR 0010).
export interface JudgeScores {
  scores: Record<string, number>;
  overall: number;
  rationale: string;
}

// The configuration that produced an Evaluation Run (PRD #38): the product
// "multi_pass" causal analysis, or the "builder_only" baseline that skips the
// Falsification Round. The dashboard compares the two side by side.
export type AnalysisMode = "multi_pass" | "builder_only";

// A recorded Evaluation Run for the dev dashboard (ADR 0010 / 0025 / 0044).
export interface EvaluationRun {
  id: string;
  scenario_id: string;
  scenario_title: string;
  status: string;
  analysis_run_status: RunStatus;
  analysis_mode: AnalysisMode;
  passed: boolean;
  experiment_metadata: ExperimentMetadata;
  check_suite_version: string;
  judge_version: string | null;
  citation_total: number;
  citation_verified: number;
  // Cost metrics recorded beside quality so better reasoning is not bought with
  // unbounded cost (PRD #38 stories 87).
  model_calls: number;
  total_tokens: number;
  latency_ms: number;
  checks: EvaluationCheck[];
  warning_code_counts: Record<string, number>;
  judge_scores: JudgeScores | null;
  error: string | null;
  created_at: string;
}

// Reasoning/retrieval provenance for one run (ADR 0038). A restricted
// diagnostics view: it exposes component versions, ordered retrieved chunk
// references, token usage, hashes, and structured outcomes — never prompts, raw
// responses, or artifact text — so causal reasoning is diagnosable without
// opening debug logs (PRD #26 user stories 69-73, 88-89).
export interface RetrievalTraceChunk {
  chunk_id: string;
  artifact_id: string;
  sequence: number;
  line_start: number;
  line_end: number;
  // Whether the role actually cited into this retrieved chunk. A retrieved-but-
  // uncited chunk (cited=false) is the signal of a model omission, distinct from
  // a chunk that was never retrieved at all (PRD user story 70).
  cited: boolean;
}

export interface RetrievalTrace {
  id: string;
  sequence: number;
  role: string;
  substep: string;
  query: string;
  strategy_version: string;
  chunk_count: number;
  cited_count: number;
  chunks: RetrievalTraceChunk[];
}

export interface ModelCallRecord {
  id: string;
  sequence: number;
  role: string;
  substep: string;
  prompt_version: string;
  schema_version: string;
  // A deterministic role (e.g. the default advisory ranker) reports its own
  // version here, with null usage/hashes.
  model_identity: string;
  input_hash: string | null;
  output_hash: string | null;
  usage: Record<string, unknown> | null;
  structured_output: Record<string, unknown> | null;
  retrieval_trace_id: string | null;
  created_at: string;
}

export interface RunDiagnostics {
  run_id: string;
  model_call_records: ModelCallRecord[];
  retrieval_traces: RetrievalTrace[];
}

export interface IncidentCreate {
  title: string;
  summary?: string | null;
  severity?: Severity | null;
}

export interface ArtifactInput {
  source_type: ArtifactSourceType;
  source_name: string;
  body: string;
}

const API_BASE = (
  process.env.NEXT_PUBLIC_POSTMORTEM_API_BASE ?? "http://localhost:8000"
).replace(/\/$/, "");
const API_TOKEN = process.env.NEXT_PUBLIC_POSTMORTEM_API_TOKEN ?? "";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (API_TOKEN) {
    headers.set("Authorization", `Bearer ${API_TOKEN}`);
  }

  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });

  if (!res.ok) {
    throw new Error(await errorMessage(res));
  }

  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (data && typeof data.detail === "string") {
      return data.detail;
    }
    if (Array.isArray(data?.detail) && data.detail[0]?.msg) {
      return data.detail[0].msg as string;
    }
  } catch {
    // fall through to the status text
  }
  return `Request failed (${res.status})`;
}

export const api = {
  listIncidents(): Promise<Incident[]> {
    return request<Incident[]>("/api/incidents");
  },

  getIncident(id: string): Promise<Incident> {
    return request<Incident>(`/api/incidents/${id}`);
  },

  listScenarios(): Promise<ScenarioSummary[]> {
    return request<ScenarioSummary[]>("/api/scenarios");
  },

  seedScenario(scenarioId: string): Promise<ScenarioSeedResult> {
    return request<ScenarioSeedResult>(`/api/scenarios/${scenarioId}/seed`, {
      method: "POST",
    });
  },

  listEvaluations(): Promise<EvaluationRun[]> {
    return request<EvaluationRun[]>("/api/evaluations");
  },

  runEvaluations(scenarioId?: string): Promise<EvaluationRun[]> {
    return request<EvaluationRun[]>("/api/evaluations", {
      method: "POST",
      body: JSON.stringify(scenarioId ? { scenario_id: scenarioId } : {}),
    });
  },

  createIncident(payload: IncidentCreate): Promise<Incident> {
    return request<Incident>("/api/incidents", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listArtifacts(incidentId: string): Promise<Artifact[]> {
    return request<Artifact[]>(`/api/incidents/${incidentId}/artifacts`);
  },

  createArtifact(incidentId: string, payload: ArtifactInput): Promise<Artifact> {
    return request<Artifact>(`/api/incidents/${incidentId}/artifacts`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  replaceArtifact(
    incidentId: string,
    artifactId: string,
    payload: ArtifactInput,
  ): Promise<Artifact> {
    return request<Artifact>(
      `/api/incidents/${incidentId}/artifacts/${artifactId}`,
      { method: "PUT", body: JSON.stringify(payload) },
    );
  },

  deleteArtifact(incidentId: string, artifactId: string): Promise<void> {
    return request<void>(`/api/incidents/${incidentId}/artifacts/${artifactId}`, {
      method: "DELETE",
    });
  },

  listAnalysisRuns(incidentId: string): Promise<AnalysisRun[]> {
    return request<AnalysisRun[]>(`/api/incidents/${incidentId}/analysis-runs`);
  },

  getAnalysisRun(incidentId: string, runId: string): Promise<AnalysisRun> {
    return request<AnalysisRun>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}`,
    );
  },

  listRunTimeline(incidentId: string, runId: string): Promise<TimelineEvent[]> {
    return request<TimelineEvent[]>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/timeline`,
    );
  },

  startAnalysisRun(
    incidentId: string,
    payload: { artifact_ids?: string[] } = {},
  ): Promise<AnalysisRun> {
    return request<AnalysisRun>(`/api/incidents/${incidentId}/analysis-runs`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listRunImpactClaims(incidentId: string, runId: string): Promise<ImpactClaim[]> {
    return request<ImpactClaim[]>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/impact`,
    );
  },

  listRunHypotheses(incidentId: string, runId: string): Promise<Hypothesis[]> {
    return request<Hypothesis[]>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/hypotheses`,
    );
  },

  reviewHypothesis(
    incidentId: string,
    runId: string,
    hypothesisId: string,
    decision: HypothesisReviewStatus,
  ): Promise<Hypothesis> {
    return request<Hypothesis>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/hypotheses/${hypothesisId}/review`,
      { method: "POST", body: JSON.stringify({ decision }) },
    );
  },

  addReviewerNote(
    incidentId: string,
    runId: string,
    payload: { body: string; hypothesis_id?: string | null },
  ): Promise<ReviewerNote> {
    return request<ReviewerNote>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/review-notes`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  getRunDiagnostics(incidentId: string, runId: string): Promise<RunDiagnostics> {
    return request<RunDiagnostics>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/diagnostics`,
    );
  },

  getRunPostmortem(incidentId: string, runId: string): Promise<Postmortem> {
    return request<Postmortem>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/postmortem`,
    );
  },

  getRunConclusion(
    incidentId: string,
    runId: string,
  ): Promise<RootCauseConclusion> {
    return request<RootCauseConclusion>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/conclusion`,
    );
  },

  finalizeRunConclusion(
    incidentId: string,
    runId: string,
    payload: {
      summary: string;
      factors: CausalFactorInput[];
      human_assumptions?: string[];
    },
  ): Promise<RootCauseConclusion> {
    return request<RootCauseConclusion>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/conclusion`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  // Disputed, not-yet-superseded conclusions across the incident (ADR 0045): the
  // candidates a new run can supersede (the new-Evidence path). 404 if the incident
  // is unknown; an empty list when nothing is disputed.
  listIncidentDisputedConclusions(incidentId: string): Promise<RootCauseConclusion[]> {
    return request<RootCauseConclusion[]>(
      `/api/incidents/${incidentId}/disputed-conclusions`,
    );
  },

  supersedeRunConclusion(
    incidentId: string,
    runId: string,
    payload: {
      summary: string;
      factors: CausalFactorInput[];
      human_assumptions?: string[];
      supersedes_conclusion_id: string;
      discrepancy_id: string;
    },
  ): Promise<RootCauseConclusion> {
    return request<RootCauseConclusion>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/conclusion/supersede`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  raiseConclusionDiscrepancy(
    incidentId: string,
    runId: string,
    payload: { explanation: string },
  ): Promise<ConclusionDiscrepancy> {
    return request<ConclusionDiscrepancy>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/conclusion/discrepancies`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  listRunRemediation(incidentId: string, runId: string): Promise<ActionItem[]> {
    return request<ActionItem[]>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/remediation`,
    );
  },

  decideRunRemediation(
    incidentId: string,
    runId: string,
    actionItemId: string,
    payload: RemediationDecisionInput,
  ): Promise<ActionItem> {
    return request<ActionItem>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/remediation/${actionItemId}/decision`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  exportRunPostmortem(
    incidentId: string,
    runId: string,
    mode: ExportMode,
  ): Promise<MarkdownExport> {
    return request<MarkdownExport>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/postmortem/export`,
      { method: "POST", body: JSON.stringify({ mode }) },
    );
  },
};
