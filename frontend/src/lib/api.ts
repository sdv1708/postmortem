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

export interface ActionItem {
  id: string;
  sequence: number;
  description: string;
  evidence_refs: EvidenceRef[];
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

export interface Hypothesis {
  id: string;
  run_id: string;
  rank: number;
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
  // Lifecycle state (ADR 0035, PRD #26): an automated run is always "provisional"
  // until a human finalizes a Root Cause Conclusion. The Review Surface labels a
  // provisional draft "Draft: Root cause not finalized".
  conclusion_status: "provisional" | "finalized";
  composer_version: string;
  timeline: TimelineEvent[];
  impact_claims: ImpactClaim[];
  hypotheses: Hypothesis[];
  created_at: string;
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

// A recorded Evaluation Run for the dev dashboard (ADR 0010 / 0025).
export interface EvaluationRun {
  id: string;
  scenario_id: string;
  scenario_title: string;
  status: string;
  analysis_run_status: RunStatus;
  passed: boolean;
  experiment_metadata: ExperimentMetadata;
  check_suite_version: string;
  judge_version: string | null;
  citation_total: number;
  citation_verified: number;
  checks: EvaluationCheck[];
  warning_code_counts: Record<string, number>;
  judge_scores: JudgeScores | null;
  error: string | null;
  created_at: string;
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

  getRunPostmortem(incidentId: string, runId: string): Promise<Postmortem> {
    return request<Postmortem>(
      `/api/incidents/${incidentId}/analysis-runs/${runId}/postmortem`,
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
