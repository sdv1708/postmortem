"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  isTerminalRunStatus,
  RUN_STAGES,
  type ActionItem,
  type AnalysisRun,
  type Artifact,
  type ArtifactSourceType,
  type CausalFactor,
  type CausalFactorInput,
  type CausalRole,
  type ChallengeSeverity,
  type ConclusionDiscrepancy,
  type ClaimSupportStatus,
  type EvidenceRef,
  type ExportMode,
  type HumanAssumption,
  type Hypothesis,
  type RemediationDecisionInput,
  type RemediationLinkInput,
  type RemediationStatus,
  type HypothesisChallenge,
  type HypothesisReviewStatus,
  type ImpactClaim,
  type Incident,
  type ModelCallRecord,
  type Postmortem,
  type RankingRationale,
  type RetrievalTrace,
  type RootCauseConclusion,
  type SupersededLink,
  type RunDiagnostics,
  type RunStage,
  type RunStageEvent,
  type RunStatus,
  type StageStatus,
  type TimelineEvent,
} from "@/lib/api";
import { SeverityBadge, StatusBadge } from "../_components/badges";

const SOURCE_TYPES: Array<{ value: ArtifactSourceType; label: string }> = [
  { value: "incident_notes", label: "Incident notes" },
  { value: "logs", label: "Logs" },
  { value: "stack_trace", label: "Stack trace" },
  { value: "deployment_notes", label: "Deployment notes" },
  { value: "other", label: "Other" },
];

type FocusedEvidence = {
  artifactId: string;
  lineStart: number;
  lineEnd: number;
};

export default function IncidentOverviewPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [incident, setIncident] = useState<Incident | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [focusedEvidence, setFocusedEvidence] = useState<FocusedEvidence | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [artifactError, setArtifactError] = useState<Error | null>(null);
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(false);

  useEffect(() => {
    if (!id) {
      return;
    }

    let active = true;
    setIsLoadingArtifacts(true);

    Promise.all([api.getIncident(id), api.listArtifacts(id)])
      .then(([incidentItem, artifactItems]) => {
        if (!active) {
          return;
        }
        setIncident(incidentItem);
        setArtifacts(artifactItems);
        setSelectedArtifactId((current) => current ?? artifactItems[0]?.id ?? null);
      })
      .catch((err: Error) => {
        if (active) {
          setError(err);
        }
      })
      .finally(() => {
        if (active) {
          setIsLoadingArtifacts(false);
        }
      });

    return () => {
      active = false;
    };
  }, [id]);

  const selectedArtifact = useMemo(
    () => artifacts.find((artifact) => artifact.id === selectedArtifactId) ?? artifacts[0] ?? null,
    [artifacts, selectedArtifactId],
  );

  async function reloadArtifacts(nextSelectedId?: string | null) {
    if (!id) {
      return;
    }
    setArtifactError(null);
    setIsLoadingArtifacts(true);
    try {
      const items = await api.listArtifacts(id);
      setArtifacts(items);
      setSelectedArtifactId(nextSelectedId ?? items[0]?.id ?? null);
      setFocusedEvidence(null);
    } catch (err) {
      setArtifactError(err instanceof Error ? err : new Error("Failed to load artifacts"));
    } finally {
      setIsLoadingArtifacts(false);
    }
  }

  async function addArtifact(payload: {
    source_type: ArtifactSourceType;
    source_name: string;
    body: string;
  }) {
    if (!id) {
      return;
    }
    setArtifactError(null);
    try {
      const artifact = await api.createArtifact(id, payload);
      await reloadArtifacts(artifact.id);
    } catch (err) {
      setArtifactError(err instanceof Error ? err : new Error("Failed to add artifact"));
    }
  }

  async function replaceArtifact(
    artifactId: string,
    payload: { source_type: ArtifactSourceType; source_name: string; body: string },
  ) {
    if (!id) {
      return;
    }
    setArtifactError(null);
    try {
      const artifact = await api.replaceArtifact(id, artifactId, payload);
      await reloadArtifacts(artifact.id);
    } catch (err) {
      setArtifactError(err instanceof Error ? err : new Error("Failed to replace artifact"));
    }
  }

  async function deleteArtifact(artifactId: string) {
    if (!id) {
      return;
    }
    setArtifactError(null);
    try {
      await api.deleteArtifact(id, artifactId);
      await reloadArtifacts(null);
    } catch (err) {
      setArtifactError(err instanceof Error ? err : new Error("Failed to delete artifact"));
    }
  }

  function focusEvidence(ref: EvidenceRef) {
    setSelectedArtifactId(ref.artifact_id);
    setFocusedEvidence({
      artifactId: ref.artifact_id,
      lineStart: ref.line_start,
      lineEnd: ref.line_end,
    });
  }

  if (!incident && !error) {
    return <DetailSkeleton />;
  }

  if (error) {
    return (
      <div className="card-padded border-rose-200 bg-rose-50/40">
        <h3 className="text-sm font-semibold text-rose-700">Failed to load incident</h3>
        <p className="mt-1 text-sm text-rose-600">{error.message}</p>
        <Link href="/incidents" className="button-secondary mt-4">
          Back to all incidents
        </Link>
      </div>
    );
  }

  if (!incident) {
    return null;
  }

  return (
    <div className="space-y-10">
      <header className="space-y-4">
        <Link
          href="/incidents"
          className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 12H5" />
            <path d="m12 19-7-7 7-7" />
          </svg>
          Back to all incidents
        </Link>

        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="space-y-3">
            <h1 className="text-3xl font-semibold tracking-tight text-slate-900">{incident.title}</h1>
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge severity={incident.severity} />
              <StatusBadge status={incident.status} />
              <span className="text-xs text-slate-500">
                Created {new Date(incident.created_at).toLocaleString()}
              </span>
            </div>
          </div>
        </div>

        {incident.summary && (
          <div className="card-padded">
            <p className="label mb-1.5">Summary</p>
            <p className="text-sm leading-relaxed text-slate-700">{incident.summary}</p>
          </div>
        )}
      </header>

      <Section
        title="Evidence"
        description="Attach logs, notes, and traces. Each line gets a permanent address you can cite from."
      >
        <EvidenceManager
          artifacts={artifacts}
          selectedArtifact={selectedArtifact}
          selectedArtifactId={selectedArtifact?.id ?? null}
          isLoading={isLoadingArtifacts}
          error={artifactError}
          focusedEvidence={
            focusedEvidence?.artifactId === selectedArtifact?.id ? focusedEvidence : null
          }
          onSelect={(artifactId) => {
            setSelectedArtifactId(artifactId);
            setFocusedEvidence(null);
          }}
          onAdd={addArtifact}
          onReplace={replaceArtifact}
          onDelete={deleteArtifact}
        />
      </Section>

      <Section
        title="Analysis runs"
        description="Start an async run. Included evidence locks so citations stay anchored."
      >
        <AnalysisRuns
          incidentId={id}
          artifactCount={artifacts.length}
          onRunStarted={() => reloadArtifacts(selectedArtifactId)}
          onFocusEvidence={focusEvidence}
        />
      </Section>

      <Section title="Postmortem" description="Drafted from evidence with line-level citations.">
        <div className="card-padded text-sm text-slate-600">
          Each succeeded analysis run above drafts a structured postmortem — summary, timeline,
          impact, ranked hypotheses, remediation, and open questions — with clean and audit
          Markdown exports. Open a run to review and export it.
        </div>
      </Section>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="h-4 w-32 animate-pulse rounded bg-slate-200" />
      <div className="h-8 w-2/3 animate-pulse rounded bg-slate-200" />
      <div className="flex gap-2">
        <div className="h-5 w-20 animate-pulse rounded-full bg-slate-200" />
        <div className="h-5 w-24 animate-pulse rounded-full bg-slate-200" />
      </div>
      <div className="card-padded">
        <div className="h-3 w-full animate-pulse rounded bg-slate-200" />
        <div className="mt-2 h-3 w-5/6 animate-pulse rounded bg-slate-200" />
      </div>
    </div>
  );
}

function EvidenceManager({
  artifacts,
  selectedArtifact,
  selectedArtifactId,
  isLoading,
  error,
  focusedEvidence,
  onSelect,
  onAdd,
  onReplace,
  onDelete,
}: {
  artifacts: Artifact[];
  selectedArtifact: Artifact | null;
  selectedArtifactId: string | null;
  isLoading: boolean;
  error: Error | null;
  focusedEvidence: FocusedEvidence | null;
  onSelect: (artifactId: string) => void;
  onAdd: (payload: { source_type: ArtifactSourceType; source_name: string; body: string }) => Promise<void>;
  onReplace: (
    artifactId: string,
    payload: { source_type: ArtifactSourceType; source_name: string; body: string },
  ) => Promise<void>;
  onDelete: (artifactId: string) => Promise<void>;
}) {
  const [sourceType, setSourceType] = useState<ArtifactSourceType>("incident_notes");
  const [sourceName, setSourceName] = useState("");
  const [body, setBody] = useState("");
  const [replaceBody, setReplaceBody] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isReplacing, setIsReplacing] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (selectedArtifact) {
      setReplaceBody(selectedArtifact.body);
    } else {
      setReplaceBody("");
    }
  }, [selectedArtifact]);

  async function submitArtifact() {
    setIsSubmitting(true);
    try {
      await onAdd({
        source_type: sourceType,
        source_name: sourceName.trim(),
        body,
      });
      setSourceName("");
      setBody("");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function submitReplacement() {
    if (!selectedArtifact) {
      return;
    }
    setIsReplacing(true);
    try {
      await onReplace(selectedArtifact.id, {
        source_type: selectedArtifact.source_type,
        source_name: selectedArtifact.source_name,
        body: replaceBody,
      });
    } finally {
      setIsReplacing(false);
    }
  }

  async function removeSelected() {
    if (!selectedArtifact) {
      return;
    }
    setIsDeleting(true);
    try {
      await onDelete(selectedArtifact.id);
    } finally {
      setIsDeleting(false);
    }
  }

  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    const text = await file.text();
    setSourceName(file.name);
    setBody(text);
    setSourceType(inferSourceType(file.name));
  }

  const replaceDirty = !!selectedArtifact && replaceBody !== selectedArtifact.body;
  const isLocked = !!selectedArtifact?.included_in_analysis_run;

  return (
    <div className="space-y-6">
      <form
        className="card overflow-hidden"
        onSubmit={(event) => {
          event.preventDefault();
          void submitArtifact();
        }}
      >
        <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50/60 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-900">Add evidence</h3>
          <span className="text-xs text-slate-500">Paste text or upload a file</span>
        </div>
        <div className="grid gap-5 p-5 md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          <div className="space-y-4">
            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-slate-700">Source type</span>
              <select
                value={sourceType}
                onChange={(event) => setSourceType(event.target.value as ArtifactSourceType)}
              >
                {SOURCE_TYPES.map((source) => (
                  <option key={source.value} value={source.value}>
                    {source.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-slate-700">Source name</span>
              <input
                value={sourceName}
                onChange={(event) => setSourceName(event.target.value)}
                placeholder="api-errors.log"
                required
              />
            </label>

            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-slate-700">Upload text file</span>
              <input
                type="file"
                accept=".log,.txt,.md,.json,.csv,text/*"
                onChange={(event) => {
                  void readFile(event);
                }}
              />
              <span className="block text-xs text-slate-500">.log, .txt, .md, .json, .csv</span>
            </label>
          </div>

          <div className="flex flex-col">
            <label className="flex flex-1 flex-col space-y-1.5">
              <span className="text-sm font-medium text-slate-700">Artifact text</span>
              <textarea
                value={body}
                onChange={(event) => setBody(event.target.value)}
                rows={10}
                className="flex-1 font-mono text-sm leading-6"
                placeholder="Paste incident notes, logs, stack traces, or deployment notes."
                required
              />
            </label>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <button
                type="submit"
                disabled={isSubmitting || !sourceName.trim() || !body.trim()}
                className="button-primary"
              >
                {isSubmitting ? "Adding..." : "Add evidence"}
              </button>
              {isLoading && (
                <span className="inline-flex items-center gap-2 text-sm text-slate-500">
                  <Spinner /> Loading evidence...
                </span>
              )}
              {error && (
                <span className="inline-flex items-center gap-1.5 text-sm text-rose-600">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="10" />
                    <path d="M12 8v4" />
                    <path d="M12 16h.01" />
                  </svg>
                  {error.message}
                </span>
              )}
            </div>
          </div>
        </div>
      </form>

      {artifacts.length === 0 && !isLoading && (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white/70 p-8 text-center">
          <h3 className="text-sm font-semibold text-slate-900">No evidence yet</h3>
          <p className="mt-1 text-sm text-slate-600">
            No evidence has been added to this incident yet.
          </p>
        </div>
      )}

      {artifacts.length > 0 && (
        <div className="grid gap-4 lg:grid-cols-[minmax(240px,300px)_minmax(0,1fr)]">
          <aside className="card overflow-hidden">
            <div className="border-b border-slate-200 bg-slate-50/60 px-4 py-2.5">
              <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Artifacts · {artifacts.length}
              </p>
            </div>
            <ul className="divide-y divide-slate-100">
              {artifacts.map((artifact) => {
                const active = artifact.id === selectedArtifactId;
                return (
                  <li key={artifact.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(artifact.id)}
                      className={`block w-full px-4 py-3 text-left transition focus:outline-none focus:ring-2 focus:ring-inset focus:ring-indigo-500/30 ${
                        active
                          ? "bg-indigo-50/60 ring-1 ring-inset ring-indigo-200"
                          : "hover:bg-slate-50"
                      }`}
                    >
                      <span
                        className={`block truncate text-sm font-medium ${
                          active ? "text-indigo-900" : "text-slate-900"
                        }`}
                      >
                        {artifact.source_name}
                      </span>
                      <span className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                        <SourceTypePill sourceType={artifact.source_type} />
                        <span>{artifact.line_count} lines</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </aside>

          {selectedArtifact && (
            <div className="space-y-4">
              <div className="card overflow-hidden">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/60 px-5 py-3">
                  <div className="min-w-0">
                    <h3 className="truncate text-sm font-semibold text-slate-900">
                      {selectedArtifact.source_name}
                    </h3>
                    <p className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                      <SourceTypePill sourceType={selectedArtifact.source_type} />
                      <span>{selectedArtifact.line_count} lines</span>
                      {isLocked && (
                        <span className="badge bg-amber-50 text-amber-700 ring-amber-200">
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                            <rect width="18" height="11" x="3" y="11" rx="2" ry="2" />
                            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                          </svg>
                          Locked · in analysis
                        </span>
                      )}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      void removeSelected();
                    }}
                    disabled={isDeleting || isLocked}
                    className="button-danger"
                  >
                    {isDeleting ? "Deleting..." : "Delete"}
                  </button>
                </div>
                <LineViewer artifact={selectedArtifact} focusedEvidence={focusedEvidence} />
              </div>

              <form
                className="card overflow-hidden"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submitReplacement();
                }}
              >
                <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50/60 px-5 py-3">
                  <h3 className="text-sm font-semibold text-slate-900">Edit evidence</h3>
                  {replaceDirty && !isLocked && (
                    <span className="text-xs font-medium text-amber-600">Unsaved changes</span>
                  )}
                </div>
                <div className="space-y-4 p-5">
                  <label className="block space-y-1.5">
                    <span className="text-sm font-medium text-slate-700">Replacement text</span>
                    <textarea
                      value={replaceBody}
                      onChange={(event) => setReplaceBody(event.target.value)}
                      rows={6}
                      disabled={isLocked}
                      className="font-mono text-sm leading-6 disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-500"
                    />
                  </label>
                  <div className="flex items-center gap-3">
                    <button
                      type="submit"
                      disabled={
                        isReplacing || isLocked || !replaceBody.trim() || !replaceDirty
                      }
                      className="button-primary"
                    >
                      {isReplacing ? "Replacing..." : "Replace evidence"}
                    </button>
                    {isLocked && (
                      <span className="text-xs text-slate-500">
                        This artifact is included in an analysis run and is locked.
                      </span>
                    )}
                  </div>
                </div>
              </form>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function LineViewer({
  artifact,
  focusedEvidence,
}: {
  artifact: Artifact;
  focusedEvidence: FocusedEvidence | null;
}) {
  useEffect(() => {
    if (!focusedEvidence) {
      return;
    }
    document
      .getElementById(`artifact-${artifact.id}-line-${focusedEvidence.lineStart}`)
      ?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [artifact.id, focusedEvidence]);

  return (
    <div className="scroll-area max-h-[28rem] overflow-auto">
      <table className="w-full border-collapse font-mono text-[13px]">
        <tbody>
          {artifact.lines.map((line) => {
            const isFocused =
              focusedEvidence !== null &&
              line.number >= focusedEvidence.lineStart &&
              line.number <= focusedEvidence.lineEnd;
            return (
              <tr
                id={`artifact-${artifact.id}-line-${line.number}`}
                key={line.number}
                className="group border-b border-slate-100 last:border-b-0"
              >
                <th
                  scope="row"
                  className={`w-14 select-none border-r border-slate-200 px-3 py-1.5 text-right align-top text-xs font-normal ${
                    isFocused
                      ? "bg-amber-100/70 text-amber-800"
                      : "bg-slate-50/70 text-slate-400 group-hover:text-slate-500"
                  }`}
                >
                  {line.number}
                </th>
                <td
                  className={`whitespace-pre-wrap break-words px-4 py-1.5 align-top leading-6 text-slate-800 ${
                    isFocused ? "bg-amber-50" : "group-hover:bg-slate-50/40"
                  }`}
                >
                  {line.text || " "}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function SourceTypePill({ sourceType }: { sourceType: ArtifactSourceType }) {
  const map: Record<ArtifactSourceType, string> = {
    incident_notes: "bg-slate-100 text-slate-700 ring-slate-200",
    logs: "bg-indigo-50 text-indigo-700 ring-indigo-200",
    stack_trace: "bg-rose-50 text-rose-700 ring-rose-200",
    deployment_notes: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    other: "bg-slate-100 text-slate-600 ring-slate-200",
  };
  return (
    <span className={`badge ${map[sourceType]}`}>{sourceTypeLabel(sourceType)}</span>
  );
}

function sourceTypeLabel(sourceType: ArtifactSourceType) {
  return SOURCE_TYPES.find((source) => source.value === sourceType)?.label ?? sourceType;
}

function inferSourceType(filename: string): ArtifactSourceType {
  const lower = filename.toLowerCase();
  if (lower.includes("stack") || lower.endsWith(".trace")) {
    return "stack_trace";
  }
  if (lower.includes("deploy") || lower.includes("release")) {
    return "deployment_notes";
  }
  if (lower.endsWith(".log") || lower.includes("log")) {
    return "logs";
  }
  return "incident_notes";
}

function AnalysisRuns({
  incidentId,
  artifactCount,
  onRunStarted,
  onFocusEvidence,
}: {
  incidentId: string;
  artifactCount: number;
  onRunStarted: () => void | Promise<void>;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const queryClient = useQueryClient();
  const runsKey = ["analysis-runs", incidentId];

  // Poll the run list while any run is still in flight (ADR 0001 / 0005). Once
  // every run is terminal, polling stops until the next mutation.
  const runsQuery = useQuery<AnalysisRun[]>({
    queryKey: runsKey,
    queryFn: () => api.listAnalysisRuns(incidentId),
    enabled: !!incidentId,
    refetchInterval: (query) => {
      const data = query.state.data;
      const hasActive = !!data && data.some((run) => !isTerminalRunStatus(run.status));
      return hasActive ? 1500 : false;
    },
  });

  const startMutation = useMutation({
    mutationFn: () => api.startAnalysisRun(incidentId),
    onSuccess: async () => {
      // Refetch the authoritative list (which includes the new run) and let the
      // parent reflect the now-locked evidence. No optimistic insert: the
      // refetched server state is the single source of truth.
      await queryClient.invalidateQueries({ queryKey: runsKey });
      await onRunStarted();
    },
  });

  const runs = runsQuery.data ?? [];
  const canStart = artifactCount > 0 && !startMutation.isPending;
  const error =
    (startMutation.error as Error | null) ?? (runsQuery.error as Error | null) ?? null;

  return (
    <div className="space-y-4">
      <div className="card-padded flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-slate-900">Run analysis on current evidence</p>
          <p className="mt-0.5 text-sm text-slate-600">
            {artifactCount === 0
              ? "Add at least one piece of evidence before starting a run."
              : `Starts a run over ${artifactCount} artifact${artifactCount === 1 ? "" : "s"} and locks them.`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {runs.length > 0 && (
            <button
              type="button"
              onClick={() => runsQuery.refetch()}
              disabled={runsQuery.isFetching}
              className="button-secondary"
            >
              {runsQuery.isFetching ? "Refreshing..." : "Refresh status"}
            </button>
          )}
          <button
            type="button"
            onClick={() => startMutation.mutate()}
            disabled={!canStart}
            className="button-primary"
          >
            {startMutation.isPending ? "Starting..." : "Start analysis run"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
          {error.message}
        </div>
      )}

      {runs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white/70 p-6 text-center">
          <h3 className="text-sm font-semibold text-slate-900">No analysis runs yet</h3>
          <p className="mt-1 text-sm text-slate-600">
            Start a run to lock the current evidence and track its status here.
          </p>
        </div>
      ) : (
        <ul className="space-y-4">
          {runs.map((run) => (
            <li key={run.id}>
              <RunStatusCard
                incidentId={incidentId}
                run={run}
                onFocusEvidence={onFocusEvidence}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RunStatusCard({
  incidentId,
  run,
  onFocusEvidence,
}: {
  incidentId: string;
  run: AnalysisRun;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const eventsByStage = new Map<RunStage, RunStageEvent>();
  // Keep the highest-sequence event per stage so a retried stage shows its
  // final attempt regardless of the array's delivery order.
  for (const event of run.stage_events) {
    const current = eventsByStage.get(event.stage);
    if (!current || event.sequence > current.sequence) {
      eventsByStage.set(event.stage, event);
    }
  }
  const isPolling = !isTerminalRunStatus(run.status);

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-slate-50/60 px-5 py-3">
        <div className="flex items-center gap-2">
          <RunStatusBadge status={run.status} />
          <span className="text-xs text-slate-500">
            {run.artifact_ids.length} artifact{run.artifact_ids.length === 1 ? "" : "s"} ·{" "}
            {run.experiment_metadata.pipeline_version}
          </span>
          {run.experiment_metadata.reasoning_budget && (
            // The recorded Reasoning Budget the Causal Analysis Stage ran under
            // (ADR 0043): a visible, comparable bound even on a successful run.
            <span
              className="badge bg-slate-100 text-slate-600 ring-slate-200"
              title="Causal analysis Reasoning Budget (per-role call ceiling, with one Targeted Repair reserved)"
            >
              budget ≤{run.experiment_metadata.reasoning_budget.max_calls_per_role} calls/role
            </span>
          )}
          {isPolling && (
            <span className="inline-flex items-center gap-1.5 text-xs text-slate-500">
              <Spinner /> Updating…
            </span>
          )}
        </div>
        <span className="text-xs text-slate-500">
          Started {new Date(run.created_at).toLocaleString()}
        </span>
      </div>

      {run.error && (
        <div className="border-b border-rose-100 bg-rose-50/60 px-5 py-2.5 text-xs text-rose-700">
          {run.failure_code && (
            // A controlled Causal Analysis Stage failure (ADR 0043): show the
            // machine-readable code and the failed substep so the failure is
            // explainable without exposing Sensitive Evidence (PRD #26 story 68).
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <span className="badge bg-rose-100 text-rose-800 ring-rose-300">
                {failureCodeLabel(run.failure_code)}
              </span>
              {run.failed_substep && (
                <span className="font-mono text-[11px] text-rose-600">
                  at {run.failed_substep}
                </span>
              )}
            </div>
          )}
          <p>{run.error}</p>
        </div>
      )}

      <ol className="divide-y divide-slate-100">
        {RUN_STAGES.map(({ stage, label }, index) => {
          const event = eventsByStage.get(stage);
          return (
            <li key={stage} className="flex items-center justify-between gap-3 px-5 py-2.5">
              <div className="flex min-w-0 items-center gap-3">
                <span className="w-4 text-right text-xs tabular-nums text-slate-400">
                  {index + 1}
                </span>
                <StageStatusIcon status={event?.status} />
                <span className="truncate text-sm text-slate-800">{label}</span>
                {event && event.attempt > 1 && (
                  <span className="badge bg-amber-50 text-amber-700 ring-amber-200">
                    retried
                  </span>
                )}
                {event?.warning_codes.map((code) => (
                  <span
                    key={code}
                    className="badge bg-amber-50 text-amber-700 ring-amber-200"
                  >
                    {code}
                  </span>
                ))}
              </div>
              <span className="shrink-0 text-xs text-slate-400">
                <StageTiming event={event} />
              </span>
            </li>
          );
        })}
      </ol>

      {run.status === "succeeded" && (
        <RunTimeline incidentId={incidentId} runId={run.id} onFocusEvidence={onFocusEvidence} />
      )}
      {run.status === "succeeded" && (
        <RunImpact incidentId={incidentId} runId={run.id} onFocusEvidence={onFocusEvidence} />
      )}
      {run.status === "succeeded" && (
        <RunHypotheses incidentId={incidentId} runId={run.id} onFocusEvidence={onFocusEvidence} />
      )}
      {run.status === "succeeded" && (
        <RunConclusion incidentId={incidentId} runId={run.id} onFocusEvidence={onFocusEvidence} />
      )}
      {run.status === "succeeded" && (
        <RunRemediation incidentId={incidentId} runId={run.id} onFocusEvidence={onFocusEvidence} />
      )}
      {run.status === "succeeded" && (
        <RunPostmortem incidentId={incidentId} runId={run.id} />
      )}
      {run.status === "succeeded" && (
        <RunDiagnosticsPanel incidentId={incidentId} runId={run.id} />
      )}
    </div>
  );
}

function RunPostmortem({ incidentId, runId }: { incidentId: string; runId: string }) {
  const [exportError, setExportError] = useState<string | null>(null);
  const [pendingMode, setPendingMode] = useState<ExportMode | null>(null);

  const postmortemQuery = useQuery<Postmortem>({
    queryKey: ["run-postmortem", incidentId, runId],
    queryFn: () => api.getRunPostmortem(incidentId, runId),
  });

  async function exportMarkdown(mode: ExportMode) {
    setExportError(null);
    setPendingMode(mode);
    try {
      const result = await api.exportRunPostmortem(incidentId, runId, mode);
      const expectedFilename = `postmortem-${runId}-${mode}.md`;
      const expectedModeLine = `**Export mode:** ${mode}`;
      if (
        result.mode !== mode ||
        result.filename !== expectedFilename ||
        !result.markdown.includes(expectedModeLine)
      ) {
        throw new Error(
          `Export response did not match the requested ${mode} mode. Please retry.`,
        );
      }
      downloadMarkdown(result.filename, result.markdown);
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export failed.");
    } finally {
      setPendingMode(null);
    }
  }

  if (postmortemQuery.isPending) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        <Spinner /> Loading postmortem…
      </div>
    );
  }

  if (postmortemQuery.isError) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-rose-600">
        Postmortem could not be loaded.
      </div>
    );
  }

  const postmortem = postmortemQuery.data;
  const insufficient = postmortem.evidence_sufficiency === "insufficient";
  const provisional = postmortem.conclusion_status === "provisional";
  const disputed = postmortem.conclusion_status === "disputed";
  const superseded = postmortem.conclusion_status === "superseded";

  return (
    <div className="border-t border-slate-200 bg-slate-50/40">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-3">
        <div className="flex items-center gap-2">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Postmortem</p>
          {provisional && (
            <span className="badge bg-indigo-50 text-indigo-700 ring-indigo-200">
              Draft: Root cause not finalized
            </span>
          )}
          {disputed && (
            <span className="badge bg-rose-50 text-rose-700 ring-rose-200">
              Disputed — not authoritative
            </span>
          )}
          {superseded && (
            <span className="badge bg-violet-50 text-violet-700 ring-violet-200">
              Superseded — not authoritative
            </span>
          )}
          {insufficient && (
            <span className="badge bg-amber-50 text-amber-700 ring-amber-200">
              insufficient evidence
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void exportMarkdown("clean")}
            disabled={pendingMode !== null}
            className="button-secondary"
          >
            {pendingMode === "clean" ? "Exporting…" : "Export clean"}
          </button>
          <button
            type="button"
            onClick={() => void exportMarkdown("audit")}
            disabled={pendingMode !== null}
            className="button-secondary"
          >
            {pendingMode === "audit" ? "Exporting…" : "Export audit"}
          </button>
        </div>
      </div>

      <p className="px-5 pt-1 text-xs text-slate-500">
        Clean export omits unsupported claims and assumptions; audit export keeps them, labeled,
        for review.
      </p>

      {exportError && (
        <p className="mx-5 mt-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {exportError}
        </p>
      )}

      <div className="space-y-3 p-5">
        {provisional && (
          <div className="flex items-start gap-2 rounded-lg border border-indigo-200 bg-indigo-50/70 p-4">
            <svg
              className="mt-0.5 shrink-0 text-indigo-600"
              width="16" height="16" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
            >
              <path d="M12 8v4" />
              <path d="M12 16h.01" />
              <circle cx="12" cy="12" r="10" />
            </svg>
            <div>
              <h4 className="text-sm font-semibold text-indigo-900">
                Draft: Root cause not finalized
              </h4>
              <p className="mt-0.5 text-xs leading-relaxed text-indigo-800">
                This is an automated provisional postmortem. It presents hypotheses and
                uncertainty for review; no root cause has been established. Only a human
                reviewer finalizes a Root Cause Conclusion.
              </p>
            </div>
          </div>
        )}
        {insufficient && (
          <div className="space-y-3 rounded-lg border border-amber-300 bg-amber-50/70 p-4">
            <div className="flex items-start gap-2">
              <svg
                className="mt-0.5 shrink-0 text-amber-600"
                width="16" height="16" viewBox="0 0 24 24" fill="none"
                stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
              >
                <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
                <path d="M12 9v4" />
                <path d="M12 17h.01" />
              </svg>
              <div>
                <h4 className="text-sm font-semibold text-amber-900">
                  Insufficient evidence — no confident root cause asserted
                </h4>
                <p className="mt-0.5 text-xs leading-relaxed text-amber-800">
                  The evidence is too sparse to support a postmortem. Rather than
                  guess, the system is asking for more evidence. The source evidence,
                  timeline, and any assumptions remain below for review.
                </p>
              </div>
            </div>
            {postmortem.evidence_gaps.length > 0 && (
              <BulletGroup label="What's missing" items={postmortem.evidence_gaps} />
            )}
            {postmortem.next_validation_steps.length > 0 && (
              <BulletGroup label="Suggested next evidence" items={postmortem.next_validation_steps} />
            )}
          </div>
        )}
        <p className="text-sm leading-relaxed text-slate-700">{postmortem.summary}</p>
        {postmortem.lessons_learned.length > 0 && (
          <BulletGroup label="Open questions" items={postmortem.lessons_learned} />
        )}
      </div>
    </div>
  );
}

// Restricted reasoning/retrieval provenance for one run (ADR 0038). Collapsed by
// default and lazily loaded so it never changes the normal Review Surface
// workflow; opening it shows how the causal analysis reasoned and what evidence
// each role saw — component versions, token usage, hashes, and ordered retrieved
// chunk references including retrieved-but-uncited ones — without exposing any
// prompt, raw response, or artifact text (PRD #26 user stories 69-73, 88-89).
function RunDiagnosticsPanel({
  incidentId,
  runId,
}: {
  incidentId: string;
  runId: string;
}) {
  const [open, setOpen] = useState(false);
  const diagnosticsQuery = useQuery<RunDiagnostics>({
    queryKey: ["run-diagnostics", incidentId, runId],
    queryFn: () => api.getRunDiagnostics(incidentId, runId),
    enabled: open,
  });

  const tracesById = useMemo(() => {
    const map = new Map<string, RetrievalTrace>();
    for (const trace of diagnosticsQuery.data?.retrieval_traces ?? []) {
      map.set(trace.id, trace);
    }
    return map;
  }, [diagnosticsQuery.data]);

  return (
    <div className="border-t border-slate-200 bg-slate-50/40">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 px-5 py-3 text-left"
        aria-expanded={open}
      >
        <span className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
            Run diagnostics
          </span>
          <span
            className="badge bg-slate-100 text-slate-600 ring-slate-200"
            title="Restricted reasoning and retrieval provenance — versions, token usage, hashes, and retrieved evidence. No prompts, raw responses, or artifact text."
          >
            restricted
          </span>
        </span>
        <span className="text-xs text-slate-500">{open ? "Hide" : "Show"}</span>
      </button>

      {open && (
        <div className="space-y-4 px-5 pb-5">
          <p className="text-xs text-slate-500">
            How the causal analysis reasoned: one record per reasoning-role call and
            the evidence each role retrieved. References and hashes only — no
            prompts, raw responses, or artifact text are stored.
          </p>

          {diagnosticsQuery.isPending && (
            <p className="text-xs text-slate-500">
              <Spinner /> Loading diagnostics…
            </p>
          )}
          {diagnosticsQuery.isError && (
            <p className="text-xs text-rose-600">Diagnostics could not be loaded.</p>
          )}

          {diagnosticsQuery.data && (
            <>
              <div className="space-y-2">
                <p className="label">
                  Model calls · {diagnosticsQuery.data.model_call_records.length}
                </p>
                <ul className="space-y-2">
                  {diagnosticsQuery.data.model_call_records.map((record) => (
                    <li key={record.id}>
                      <ModelCallRow
                        record={record}
                        trace={
                          record.retrieval_trace_id
                            ? tracesById.get(record.retrieval_trace_id) ?? null
                            : null
                        }
                      />
                    </li>
                  ))}
                </ul>
              </div>

              <div className="space-y-2">
                <p className="label">
                  Retrieval traces · {diagnosticsQuery.data.retrieval_traces.length}
                </p>
                <ul className="space-y-2">
                  {diagnosticsQuery.data.retrieval_traces.map((trace) => (
                    <li key={trace.id}>
                      <RetrievalTraceRow trace={trace} />
                    </li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

const ROLE_LABELS: Record<string, string> = {
  incident_facts: "Incident facts",
  builder: "Builder",
  falsifier: "Falsifier",
  support_verifier: "Support verifier",
  ranker: "Ranker",
};

function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

function usageSummary(usage: Record<string, unknown> | null): string | null {
  if (!usage) {
    return null;
  }
  const total = usage["total_tokens"];
  if (typeof total === "number") {
    return `${total} tokens`;
  }
  const keys = Object.keys(usage);
  return keys.length > 0 ? `${keys.length} usage field${keys.length === 1 ? "" : "s"}` : null;
}

function ModelCallRow({
  record,
  trace,
}: {
  record: ModelCallRecord;
  trace: RetrievalTrace | null;
}) {
  const usage = usageSummary(record.usage);
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge bg-indigo-50 text-indigo-700 ring-indigo-200">
          {roleLabel(record.role)}
        </span>
        <span className="font-mono text-xs text-slate-500">{record.substep}</span>
        <span className="text-xs text-slate-500">model: {record.model_identity}</span>
        {usage ? (
          <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-200">{usage}</span>
        ) : (
          <span
            className="badge bg-slate-100 text-slate-500 ring-slate-200"
            title="A deterministic role makes no model call, so it reports no token usage."
          >
            no model call
          </span>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
        <span>prompt: {record.prompt_version}</span>
        <span>schema: {record.schema_version}</span>
        {record.input_hash && (
          <span title={`prompt hash ${record.input_hash}`}>
            in#{record.input_hash.slice(0, 8)}
          </span>
        )}
        {record.output_hash && (
          <span title={`response hash ${record.output_hash}`}>
            out#{record.output_hash.slice(0, 8)}
          </span>
        )}
        {trace && (
          <span title="Linked retrieval trace for this call">
            retrieved {trace.cited_count}/{trace.chunk_count} chunks cited
          </span>
        )}
      </div>
      {record.structured_output && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-xs text-slate-500">
            Structured outcome
          </summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded bg-slate-50 p-2 text-[11px] leading-snug text-slate-600">
            {JSON.stringify(record.structured_output, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function RetrievalTraceRow({ trace }: { trace: RetrievalTrace }) {
  const uncited = trace.chunk_count - trace.cited_count;
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge bg-violet-50 text-violet-700 ring-violet-200">
          {roleLabel(trace.role)}
        </span>
        <span className="font-mono text-xs text-slate-500">{trace.substep}</span>
        <span className="text-xs text-slate-500">strategy: {trace.strategy_version}</span>
        <span className="badge bg-slate-100 text-slate-600 ring-slate-200">
          {trace.cited_count}/{trace.chunk_count} cited
        </span>
        {uncited > 0 && (
          <span
            className="badge bg-amber-50 text-amber-700 ring-amber-200"
            title="These chunks were retrieved and shown to the role but cited by nothing — a model omission, distinct from evidence that was never retrieved."
          >
            {uncited} retrieved · uncited
          </span>
        )}
      </div>
      <p className="mt-1 text-xs text-slate-500">{trace.query}</p>
      {trace.chunks.length > 0 && (
        <ul className="mt-1.5 flex flex-wrap gap-1.5">
          {trace.chunks.map((chunk) => (
            <li
              key={chunk.chunk_id}
              className={`badge ${
                chunk.cited
                  ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                  : "bg-slate-100 text-slate-500 ring-slate-200"
              }`}
              title={
                chunk.cited
                  ? "Cited by this role"
                  : "Retrieved but not cited by this role"
              }
            >
              #{chunk.sequence} L{chunk.line_start}-{chunk.line_end}
              {chunk.cited ? " ✓" : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function downloadMarkdown(filename: string, markdown: string) {
  const blob = new Blob([markdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function RunHypotheses({
  incidentId,
  runId,
  onFocusEvidence,
}: {
  incidentId: string;
  runId: string;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const queryClient = useQueryClient();
  const [reviewError, setReviewError] = useState<string | null>(null);
  const hypothesesKey = ["run-hypotheses", incidentId, runId];
  const hypothesesQuery = useQuery<Hypothesis[]>({
    queryKey: hypothesesKey,
    queryFn: () => api.listRunHypotheses(incidentId, runId),
  });

  const reviewMutation = useMutation({
    mutationFn: ({
      hypothesisId,
      decision,
    }: {
      hypothesisId: string;
      decision: HypothesisReviewStatus;
    }) => api.reviewHypothesis(incidentId, runId, hypothesisId, decision),
    onMutate: () => {
      setReviewError(null);
    },
    onSuccess: (updated) => {
      // The accept/reject decision never rewrites claims (ADR 0016); patch only
      // the reviewed hypothesis's status into the cached list.
      queryClient.setQueryData<Hypothesis[]>(hypothesesKey, (current) =>
        current?.map((h) => (h.id === updated.id ? updated : h)),
      );
    },
    onError: (error) => {
      setReviewError(
        error instanceof Error ? error.message : "Hypothesis review could not be saved.",
      );
    },
  });
  const noteMutation = useMutation({
    mutationFn: ({
      hypothesisId,
      body,
    }: {
      hypothesisId: string;
      body: string;
    }) => api.addReviewerNote(incidentId, runId, { hypothesis_id: hypothesisId, body }),
    onMutate: () => {
      setReviewError(null);
    },
    onSuccess: (note) => {
      queryClient.setQueryData<Hypothesis[]>(hypothesesKey, (current) =>
        current?.map((h) =>
          h.id === note.hypothesis_id
            ? { ...h, reviewer_notes: [...h.reviewer_notes, note] }
            : h,
        ),
      );
    },
    onError: (error) => {
      setReviewError(
        error instanceof Error ? error.message : "Reviewer note could not be saved.",
      );
    },
  });

  if (hypothesesQuery.isPending) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        <Spinner /> Loading hypotheses…
      </div>
    );
  }

  if (hypothesesQuery.isError) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-rose-600">
        Hypotheses could not be loaded.
      </div>
    );
  }

  const hypotheses = hypothesesQuery.data ?? [];
  if (hypotheses.length === 0) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        No RCA hypotheses: the configured model returned none for this evidence.
      </div>
    );
  }

  // Separate the authoritative narrative (supported + partially-supported) from
  // unsupported claims, which stay visible as auditable Review Findings rather
  // than being presented as fact (ADR 0014 / 0015).
  const authoritative = hypotheses.filter((h) => h.support_status !== "unsupported");
  const findings = hypotheses.filter((h) => h.support_status === "unsupported");

  const renderHypothesis = (hypothesis: Hypothesis) => (
    <li key={hypothesis.id}>
      <HypothesisCard
        hypothesis={hypothesis}
        onReview={(decision) =>
          reviewMutation.mutate({ hypothesisId: hypothesis.id, decision })
        }
        isReviewing={
          reviewMutation.isPending &&
          reviewMutation.variables?.hypothesisId === hypothesis.id
        }
        onAddNote={(body) =>
          noteMutation.mutateAsync({ hypothesisId: hypothesis.id, body }).then(() => undefined)
        }
        isSavingNote={
          noteMutation.isPending &&
          noteMutation.variables?.hypothesisId === hypothesis.id
        }
        onFocusEvidence={onFocusEvidence}
      />
    </li>
  );

  return (
    <div className="border-t border-slate-200">
      {reviewError && (
        <p className="mx-5 mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {reviewError}
        </p>
      )}
      {authoritative.length > 0 && (
        <>
          <p className="px-5 pt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
            RCA hypotheses · {authoritative.length}
          </p>
          <ol className="space-y-4 p-5">{authoritative.map(renderHypothesis)}</ol>
        </>
      )}
      {findings.length > 0 && (
        <div className="border-t border-slate-200 bg-slate-50/50">
          <p className="px-5 pt-3 text-xs font-medium uppercase tracking-wide text-rose-700">
            Review findings · unsupported · {findings.length}
          </p>
          <p className="px-5 pt-1 text-xs text-slate-500">
            The cited evidence does not support these claims. They stay visible for
            audit but are not part of the authoritative postmortem narrative.
          </p>
          <ol className="space-y-4 p-5">{findings.map(renderHypothesis)}</ol>
        </div>
      )}
    </div>
  );
}

function HypothesisCard({
  hypothesis,
  onReview,
  isReviewing,
  onAddNote,
  isSavingNote,
  onFocusEvidence,
}: {
  hypothesis: Hypothesis;
  onReview: (decision: HypothesisReviewStatus) => void;
  isReviewing: boolean;
  onAddNote: (body: string) => Promise<void>;
  isSavingNote: boolean;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const [noteBody, setNoteBody] = useState("");

  async function submitNote() {
    const body = noteBody.trim();
    if (!body) {
      return;
    }
    await onAddNote(body);
    setNoteBody("");
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold tabular-nums text-slate-600"
            title={
              hypothesis.advisory_rank !== null
                ? `Advisory rank ${hypothesis.advisory_rank} · generated #${hypothesis.rank}`
                : `Generated #${hypothesis.rank}`
            }
          >
            {hypothesis.advisory_rank ?? hypothesis.rank}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-sm font-semibold text-slate-900">{hypothesis.title}</h4>
              {hypothesis.leading_but_critically_challenged && (
                <span
                  className="badge bg-rose-50 text-rose-700 ring-rose-200"
                  title="Ranked first by plausibility, but an unresolved critical challenge means it cannot be presented as the failure mechanism without an explicit human override."
                >
                  Leading but critically challenged
                </span>
              )}
              {hypothesis.origin === "proposed" && (
                <span
                  className="badge bg-violet-50 text-violet-700 ring-violet-200"
                  title="Introduced by the falsifier's bounded alternative-expansion round, then challenged and reviewed like any other hypothesis. Not a root cause."
                >
                  proposed alternative
                </span>
              )}
              {hypothesis.assumption && (
                <span className="badge bg-amber-50 text-amber-700 ring-amber-200">assumption</span>
              )}
              <ClaimSupportBadge status={hypothesis.support_status} />
              <ReviewStatusBadge status={hypothesis.review_status} />
              {hypothesis.challenge && (
                <ChallengeSeverityBadge severity={hypothesis.challenge.severity} />
              )}
            </div>
            <p className="mt-1 text-sm leading-relaxed text-slate-700">{hypothesis.summary}</p>
            <SupportRationale
              status={hypothesis.support_status}
              rationale={hypothesis.support_rationale}
            />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={() => onReview("accepted")}
            disabled={isReviewing || hypothesis.review_status === "accepted"}
            className="button-secondary"
          >
            Accept
          </button>
          <button
            type="button"
            onClick={() => onReview("rejected")}
            disabled={isReviewing || hypothesis.review_status === "rejected"}
            className="button-secondary"
          >
            Reject
          </button>
        </div>
      </div>

      <div className="space-y-4 px-4 py-3">
        {hypothesis.supporting_evidence.length > 0 && (
          <EvidenceGroup
            label="Supporting evidence"
            refs={hypothesis.supporting_evidence}
            onFocusEvidence={onFocusEvidence}
          />
        )}
        {hypothesis.contradicting_evidence.length > 0 && (
          <EvidenceGroup
            label="Contradicting evidence"
            refs={hypothesis.contradicting_evidence}
            onFocusEvidence={onFocusEvidence}
          />
        )}

        {hypothesis.challenge && (
          <ChallengePanel challenge={hypothesis.challenge} onFocusEvidence={onFocusEvidence} />
        )}

        {hypothesis.ranking_rationale && (
          <RankingRationalePanel
            rationale={hypothesis.ranking_rationale}
            advisoryRank={hypothesis.advisory_rank}
            builderRank={hypothesis.rank}
          />
        )}

        {hypothesis.action_items.length > 0 && (
          <div className="space-y-1.5">
            <p className="label">Remediation proposals</p>
            <ul className="space-y-2">
              {hypothesis.action_items.map((item) => (
                <li key={item.id} className="text-sm text-slate-700">
                  <span className="inline-flex flex-wrap items-center gap-2">
                    <span>{item.description}</span>
                    <RemediationStatusBadge status={item.review_status} />
                  </span>
                  {item.link && (
                    <p className="mt-0.5 text-xs text-slate-500">↳ {item.link.label}</p>
                  )}
                  {item.evidence_refs.length > 0 && (
                    <EvidenceRefList
                      refs={item.evidence_refs}
                      onFocusEvidence={onFocusEvidence}
                    />
                  )}
                </li>
              ))}
            </ul>
            <p className="text-xs text-slate-400">
              Decide each proposal in the Remediation review panel below.
            </p>
          </div>
        )}

        {hypothesis.unknowns.length > 0 && (
          <BulletGroup label="Unknowns" items={hypothesis.unknowns} />
        )}
        {hypothesis.validation_steps.length > 0 && (
          <BulletGroup label="Validation steps" items={hypothesis.validation_steps} />
        )}

        <div className="space-y-2 border-t border-slate-100 pt-3">
          <p className="label">Reviewer notes</p>
          {hypothesis.reviewer_notes.length > 0 && (
            <ul className="space-y-2">
              {hypothesis.reviewer_notes.map((note) => (
                <li
                  key={note.id}
                  className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
                >
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                    {note.body}
                  </p>
                  <p className="mt-1 text-xs text-slate-400">
                    {new Date(note.created_at).toLocaleString()}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <form
            className="space-y-2"
            onSubmit={(event) => {
              event.preventDefault();
              void submitNote();
            }}
          >
            <textarea
              value={noteBody}
              onChange={(event) => setNoteBody(event.target.value)}
              rows={3}
              placeholder="Add reviewer context."
              className="text-sm leading-relaxed"
            />
            <button
              type="submit"
              disabled={isSavingNote || !noteBody.trim()}
              className="button-secondary"
            >
              {isSavingNote ? "Saving..." : "Add note"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

// The human Root Cause Conclusion (ADR 0039). The system never declares a root
// cause — it ranks hypotheses; only a human finalizes a conclusion (PRD #26
// stories 30, 90). This panel renders the finalized conclusion when one exists,
// distinct from the advisory ranking above, or a finalization form over the
// accepted, evidence-backed hypotheses otherwise. Acceptance and finalization are
// deliberately separate actions.
const CAUSAL_ROLE_OPTIONS: Array<{ value: CausalRole | "none"; label: string }> = [
  { value: "none", label: "Not a cause" },
  { value: "failure_mechanism", label: "Failure mechanism" },
  { value: "trigger", label: "Trigger" },
  { value: "amplifying_condition", label: "Amplifying condition" },
];

function hypothesisIsFinalizable(hypothesis: Hypothesis): boolean {
  // The trust floor mirrors the backend: an accepted hypothesis with supported or
  // partial claim support and at least one verified supporting citation.
  return (
    hypothesis.review_status === "accepted" &&
    (hypothesis.support_status === "supported" ||
      hypothesis.support_status === "partial") &&
    hypothesis.supporting_evidence.some((ref) => ref.verifier_status === "verified")
  );
}

function RunConclusion({
  incidentId,
  runId,
  onFocusEvidence,
}: {
  incidentId: string;
  runId: string;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const queryClient = useQueryClient();
  const conclusionQuery = useQuery<RootCauseConclusion | null>({
    queryKey: ["run-conclusion", incidentId, runId],
    // A 404 means "not finalized yet", not an error — surface the form instead.
    queryFn: async () => {
      try {
        return await api.getRunConclusion(incidentId, runId);
      } catch {
        return null;
      }
    },
  });
  const hypothesesQuery = useQuery<Hypothesis[]>({
    queryKey: ["run-hypotheses", incidentId, runId],
    queryFn: () => api.listRunHypotheses(incidentId, runId),
  });
  // Disputed conclusions elsewhere in the incident can be superseded from this run
  // (the new-Evidence path, ADR 0045). Only relevant while this run has no conclusion
  // of its own; the finalize form offers them as supersede targets.
  const disputedQuery = useQuery<RootCauseConclusion[]>({
    queryKey: ["incident-disputed-conclusions", incidentId],
    queryFn: () => api.listIncidentDisputedConclusions(incidentId),
  });

  if (conclusionQuery.isPending) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        <Spinner /> Loading root cause conclusion…
      </div>
    );
  }

  const conclusion = conclusionQuery.data ?? null;
  if (conclusion) {
    return (
      <ConclusionPanel
        incidentId={incidentId}
        runId={runId}
        conclusion={conclusion}
        hypotheses={hypothesesQuery.data ?? []}
        onFocusEvidence={onFocusEvidence}
        onDisputed={() => {
          void queryClient.invalidateQueries({
            queryKey: ["run-conclusion", incidentId, runId],
          });
          void queryClient.invalidateQueries({
            queryKey: ["run-postmortem", incidentId, runId],
          });
          void queryClient.invalidateQueries({
            queryKey: ["run-hypotheses", incidentId, runId],
          });
        }}
      />
    );
  }

  return (
    <ConclusionForm
      incidentId={incidentId}
      runId={runId}
      hypotheses={hypothesesQuery.data ?? []}
      // Cross-run supersede targets: other runs' disputed conclusions (ADR 0045).
      supersedeCandidates={(disputedQuery.data ?? []).filter((c) => c.run_id !== runId)}
      onFinalized={() => {
        void queryClient.invalidateQueries({ queryKey: ["run-conclusion", incidentId, runId] });
        void queryClient.invalidateQueries({ queryKey: ["run-postmortem", incidentId, runId] });
        // A cross-run supersede resolves another run's dispute, so refresh both the
        // incident candidate list and the predecessor run's conclusion/postmortem.
        void queryClient.invalidateQueries({
          queryKey: ["incident-disputed-conclusions", incidentId],
        });
        void queryClient.invalidateQueries({ queryKey: ["run-conclusion", incidentId] });
        void queryClient.invalidateQueries({ queryKey: ["run-postmortem", incidentId] });
      }}
    />
  );
}

// Review of generated Remediation Proposals (ADR 0041). Generated remediation is a
// candidate, not committed work (CONTEXT "Remediation Proposal vs Committed
// Action"): a reviewer accepts, rejects, or defers each proposal after the run, and
// an accepted one must link to a finalized Causal Factor or a documented Evidence
// Gap (PRD #26 stories 51-53). This review is separate from the falsification round.
type RemediationLinkOption = {
  value: string;
  label: string;
  payload: RemediationLinkInput;
};

function RunRemediation({
  incidentId,
  runId,
  onFocusEvidence,
}: {
  incidentId: string;
  runId: string;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const remediationKey = ["run-remediation", incidentId, runId];
  const proposalsQuery = useQuery<ActionItem[]>({
    queryKey: remediationKey,
    queryFn: () => api.listRunRemediation(incidentId, runId),
  });
  // The finalized conclusion (if any) supplies Causal Factor link targets; a 404
  // means none is finalized yet, which is fine — Evidence Gaps may still be linked.
  const conclusionQuery = useQuery<RootCauseConclusion | null>({
    queryKey: ["run-conclusion", incidentId, runId],
    queryFn: async () => {
      try {
        return await api.getRunConclusion(incidentId, runId);
      } catch {
        return null;
      }
    },
  });
  // Hypotheses carry the falsifier's Evidence Gaps (via their challenge), the other
  // accepted-link target.
  const hypothesesQuery = useQuery<Hypothesis[]>({
    queryKey: ["run-hypotheses", incidentId, runId],
    queryFn: () => api.listRunHypotheses(incidentId, runId),
  });

  const decideMutation = useMutation({
    mutationFn: ({
      actionItemId,
      payload,
    }: {
      actionItemId: string;
      payload: RemediationDecisionInput;
    }) => api.decideRunRemediation(incidentId, runId, actionItemId, payload),
    onMutate: () => setError(null),
    onSuccess: (updated) => {
      queryClient.setQueryData<ActionItem[]>(remediationKey, (current) =>
        current?.map((p) => (p.id === updated.id ? updated : p)),
      );
      // Keep the inline badges under each hypothesis and the export in sync.
      void queryClient.invalidateQueries({ queryKey: ["run-hypotheses", incidentId, runId] });
      void queryClient.invalidateQueries({ queryKey: ["run-postmortem", incidentId, runId] });
    },
    onError: (err) =>
      setError(err instanceof Error ? err.message : "The decision could not be recorded."),
  });

  const linkOptions = useMemo<RemediationLinkOption[]>(() => {
    const options: RemediationLinkOption[] = [];
    const conclusion = conclusionQuery.data ?? null;
    if (conclusion) {
      const factors = [
        conclusion.failure_mechanism,
        ...conclusion.triggers,
        ...conclusion.amplifying_conditions,
      ];
      for (const factor of factors) {
        options.push({
          value: `cf:${factor.id}`,
          label: `Causal factor · ${factor.role.replace(/_/g, " ")}: ${factor.title}`,
          payload: { kind: "causal_factor", causal_factor_id: factor.id },
        });
      }
    }
    for (const hypothesis of hypothesesQuery.data ?? []) {
      const challenge = hypothesis.challenge;
      if (!challenge) {
        continue;
      }
      challenge.evidence_gaps.forEach((gap, index) => {
        options.push({
          value: `eg:${challenge.id}:${index}`,
          label: `Evidence gap · ${gap}`,
          payload: {
            kind: "evidence_gap",
            evidence_gap_challenge_id: challenge.id,
            evidence_gap_index: index,
          },
        });
      });
    }
    return options;
  }, [conclusionQuery.data, hypothesesQuery.data]);

  if (proposalsQuery.isPending) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        <Spinner /> Loading remediation proposals…
      </div>
    );
  }

  const proposals = proposalsQuery.data ?? [];

  return (
    <div className="border-t border-slate-200">
      <p className="px-5 pt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
        Remediation review · {proposals.length}
      </p>
      <p className="px-5 pt-1 text-xs text-slate-500">
        Generated remediation is a proposal, not committed work. Accept, reject, or
        defer each one; accepting requires linking it to a finalized causal factor or
        a documented evidence gap.
      </p>
      {error && (
        <p className="mx-5 mt-3 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </p>
      )}
      {proposals.length === 0 ? (
        <p className="px-5 py-3 text-xs text-slate-500">
          No remediation was generated for this run.
        </p>
      ) : (
        <ul className="space-y-3 p-5">
          {proposals.map((proposal) => (
            <li key={proposal.id}>
              <RemediationProposalRow
                proposal={proposal}
                linkOptions={linkOptions}
                isDeciding={
                  decideMutation.isPending &&
                  decideMutation.variables?.actionItemId === proposal.id
                }
                onDecide={(payload) =>
                  decideMutation.mutate({ actionItemId: proposal.id, payload })
                }
                onFocusEvidence={onFocusEvidence}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RemediationProposalRow({
  proposal,
  linkOptions,
  isDeciding,
  onDecide,
  onFocusEvidence,
}: {
  proposal: ActionItem;
  linkOptions: RemediationLinkOption[];
  isDeciding: boolean;
  onDecide: (payload: RemediationDecisionInput) => void;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const [linkValue, setLinkValue] = useState("");
  const [rationale, setRationale] = useState(proposal.decision_rationale ?? "");

  function accept() {
    const option = linkOptions.find((o) => o.value === linkValue);
    if (!option) {
      return;
    }
    onDecide({
      decision: "accepted",
      link: option.payload,
      rationale: rationale.trim() || undefined,
    });
  }

  function decideWithout(decision: RemediationStatus) {
    onDecide({ decision, rationale: rationale.trim() || undefined });
  }

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="inline-flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-slate-800">{proposal.description}</span>
            <RemediationStatusBadge status={proposal.review_status} />
          </span>
          {proposal.link && (
            <p className="mt-0.5 text-xs text-slate-500">↳ {proposal.link.label}</p>
          )}
          {proposal.decided_by && (
            <p className="mt-0.5 text-xs text-slate-400">
              Decided by {proposal.decided_by_display || proposal.decided_by}
              {proposal.decided_at
                ? ` on ${new Date(proposal.decided_at).toLocaleString()}`
                : ""}
            </p>
          )}
          {proposal.evidence_refs.length > 0 && (
            <EvidenceRefList refs={proposal.evidence_refs} onFocusEvidence={onFocusEvidence} />
          )}
        </div>
      </div>

      <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label={`Accept link target for ${proposal.description}`}
            value={linkValue}
            onChange={(event) => setLinkValue(event.target.value)}
            className="min-w-0 flex-1 rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
          >
            <option value="">Link to a causal factor or evidence gap…</option>
            {linkOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={accept}
            disabled={isDeciding || !linkValue}
            className="button-secondary"
            title={
              linkOptions.length === 0
                ? "Finalize a conclusion or note an evidence gap first to link an accepted proposal."
                : undefined
            }
          >
            Accept proposal
          </button>
          <button
            type="button"
            onClick={() => decideWithout("rejected")}
            disabled={isDeciding || proposal.review_status === "rejected"}
            className="button-secondary"
          >
            Reject proposal
          </button>
          <button
            type="button"
            onClick={() => decideWithout("deferred")}
            disabled={isDeciding || proposal.review_status === "deferred"}
            className="button-secondary"
          >
            Defer proposal
          </button>
        </div>
        <input
          type="text"
          value={rationale}
          onChange={(event) => setRationale(event.target.value)}
          placeholder="Optional decision rationale"
          className="w-full rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
        />
      </div>
    </div>
  );
}

function ConclusionPanel({
  incidentId,
  runId,
  conclusion,
  hypotheses,
  onFocusEvidence,
  onDisputed,
}: {
  incidentId: string;
  runId: string;
  conclusion: RootCauseConclusion;
  hypotheses: Hypothesis[];
  onFocusEvidence: (ref: EvidenceRef) => void;
  onDisputed: () => void;
}) {
  const who = conclusion.finalized_by_display || conclusion.finalized_by;
  // This conclusion has been replaced by a Superseding Conclusion (ADR 0045):
  // authority moved to the successor, so it is no longer authoritative even though
  // its own discrepancy is now resolved. Distinct from "disputed" (still open).
  const superseded = conclusion.superseded_by !== null;
  const disputed = conclusion.disputed && !superseded;
  const headingTone = superseded
    ? "text-violet-700"
    : disputed
      ? "text-rose-700"
      : "text-emerald-700";
  return (
    <div
      className={`border-t border-slate-200 ${
        superseded ? "bg-violet-50/30" : disputed ? "bg-rose-50/30" : "bg-emerald-50/30"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 px-5 pt-3">
        <p className={`text-xs font-medium uppercase tracking-wide ${headingTone}`}>
          Root Cause Conclusion
        </p>
        {superseded ? (
          <span className="badge bg-violet-50 text-violet-700 ring-violet-200">superseded</span>
        ) : disputed ? (
          <span className="badge bg-rose-50 text-rose-700 ring-rose-200">disputed</span>
        ) : (
          <span className="badge bg-emerald-50 text-emerald-700 ring-emerald-200">
            finalized by human
          </span>
        )}
        {conclusion.supersedes !== null && !superseded && (
          <span className="badge bg-violet-50 text-violet-700 ring-violet-200">
            superseding conclusion
          </span>
        )}
      </div>
      <p className="px-5 pt-1 text-xs text-slate-500">
        The human reviewer&apos;s decision — distinct from the advisory ranking above,
        which only recommends plausible candidates. Finalized by {who} on{" "}
        {new Date(conclusion.finalized_at).toLocaleString()}.
      </p>

      {disputed && (
        <div className="mx-5 mt-3 flex items-start gap-2 rounded-lg border border-rose-300 bg-rose-50/80 p-4">
          <svg
            className="mt-0.5 shrink-0 text-rose-600"
            width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          >
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
          </svg>
          <div>
            <h4 className="text-sm font-semibold text-rose-900">
              Disputed — returned to unresolved review
            </h4>
            <p className="mt-0.5 text-xs leading-relaxed text-rose-800">
              A reviewer raised an open discrepancy against this conclusion. It is
              preserved below for audit but is no longer authoritative. The immutable
              conclusion is never edited — disagreement is recorded as an append-only
              discrepancy.
            </p>
          </div>
        </div>
      )}

      {superseded && conclusion.superseded_by && (
        <div className="mx-5 mt-3 flex items-start gap-2 rounded-lg border border-violet-300 bg-violet-50/80 p-4">
          <svg
            className="mt-0.5 shrink-0 text-violet-600"
            width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          >
            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
            <path d="M21 3v5h-5" />
          </svg>
          <div>
            <h4 className="text-sm font-semibold text-violet-900">
              Superseded — replaced by a newer conclusion
            </h4>
            <p className="mt-0.5 text-xs leading-relaxed text-violet-800">
              A reviewer resolved the dispute by finalizing a Superseding Conclusion.
              This conclusion is preserved for audit but is no longer authoritative.{" "}
              {conclusion.superseded_by.disputed ? (
                // The successor is itself disputed (or further superseded): authority
                // is the undisputed tail, so there is currently no authoritative
                // conclusion (ADR 0045).
                <>
                  The replacement conclusion is itself disputed, so the incident has no
                  authoritative conclusion and is under unresolved review.
                </>
              ) : (
                <>
                  The authoritative conclusion was finalized in analysis run{" "}
                  <code className="rounded bg-violet-100 px-1">
                    {conclusion.superseded_by.run_id}
                  </code>
                  .
                </>
              )}
            </p>
          </div>
        </div>
      )}

      <div className="space-y-4 p-5">
        <p className="text-sm leading-relaxed text-slate-700">{conclusion.summary}</p>
        <CausalFactorGroup
          label="Failure mechanism"
          factors={[conclusion.failure_mechanism]}
          onFocusEvidence={onFocusEvidence}
        />
        {conclusion.triggers.length > 0 && (
          <CausalFactorGroup
            label="Triggers"
            factors={conclusion.triggers}
            onFocusEvidence={onFocusEvidence}
          />
        )}
        {conclusion.amplifying_conditions.length > 0 && (
          <CausalFactorGroup
            label="Amplifying conditions"
            factors={conclusion.amplifying_conditions}
            onFocusEvidence={onFocusEvidence}
          />
        )}

        {conclusion.human_assumptions.length > 0 && (
          <HumanAssumptionList assumptions={conclusion.human_assumptions} />
        )}

        {conclusion.discrepancies.length > 0 && (
          <div className="space-y-2 border-t border-rose-100 pt-3">
            <p className="label text-rose-700">Discrepancies · {conclusion.discrepancies.length}</p>
            <ul className="space-y-2">
              {conclusion.discrepancies.map((discrepancy) => (
                <li
                  key={discrepancy.id}
                  className="rounded-lg border border-rose-200 bg-rose-50/60 px-3 py-2"
                >
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-rose-900">
                    {discrepancy.explanation}
                  </p>
                  <p className="mt-1 text-xs text-rose-500">
                    Raised by {discrepancy.raised_by_display || discrepancy.raised_by} on{" "}
                    {new Date(discrepancy.created_at).toLocaleString()}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* The complete superseding chain for audit (ADR 0045, PRD #26 story 48):
            the predecessors this conclusion replaced, and the successor that replaced
            it (when this run's conclusion was the one superseded). */}
        {(conclusion.history.length > 0 || conclusion.superseded_by) && (
          <SupersedingChain
            history={conclusion.history}
            supersededBy={conclusion.superseded_by}
          />
        )}

        {/* A disputed conclusion can be disputed further (append-only) or resolved by
            superseding it. A superseded conclusion is already resolved — neither form
            applies; review continues on the authoritative successor. */}
        {!superseded && (
          <DiscrepancyForm
            incidentId={incidentId}
            runId={runId}
            disputed={disputed}
            onRaised={onDisputed}
          />
        )}
      </div>

      {disputed && (
        <ConclusionForm
          incidentId={incidentId}
          runId={runId}
          hypotheses={hypotheses}
          onFinalized={onDisputed}
          supersede={{
            conclusionId: conclusion.id,
            // Resolve the most recent open discrepancy; any of the predecessor's own
            // discrepancies is a valid link, and the latest reflects the live concern.
            discrepancyId:
              conclusion.discrepancies[conclusion.discrepancies.length - 1].id,
          }}
        />
      )}
    </div>
  );
}

// The superseding chain for audit (ADR 0045): predecessors this conclusion replaced,
// oldest first, and the authoritative successor when this conclusion was superseded.
function SupersedingChain({
  history,
  supersededBy,
}: {
  history: SupersededLink[];
  supersededBy: SupersededLink | null;
}) {
  const entries: Array<{ link: SupersededLink; label: string }> = [
    ...history.map((link) => ({ link, label: "Earlier conclusion" })),
    ...(supersededBy ? [{ link: supersededBy, label: "Superseded by" }] : []),
  ];
  return (
    <div className="space-y-2 border-t border-violet-100 pt-3">
      <p className="label text-violet-700">Superseding chain · {entries.length}</p>
      <ul className="space-y-2">
        {entries.map(({ link, label }) => (
          <li
            key={link.id}
            className="rounded-lg border border-violet-200 bg-violet-50/50 px-3 py-2"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium uppercase tracking-wide text-violet-700">
                {label}
              </span>
              {link.disputed && (
                <span className="badge bg-rose-50 text-rose-700 ring-rose-200">disputed</span>
              )}
              <span className="text-xs text-slate-400">run {link.run_id}</span>
            </div>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
              {link.summary}
            </p>
            <p className="mt-0.5 text-xs text-slate-400">
              Finalized by {link.finalized_by_display || link.finalized_by} on{" "}
              {new Date(link.finalized_at).toLocaleString()}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

// Flag an immutable conclusion as disputed (ADR 0040). Raising a discrepancy never
// edits the conclusion — it appends an audit-preserved flag that returns review to
// unresolved (PRD #26 stories 44-46). Always available because discrepancies are
// append-only; a reviewer may record more than one concern.
function DiscrepancyForm({
  incidentId,
  runId,
  disputed,
  onRaised,
}: {
  incidentId: string;
  runId: string;
  disputed: boolean;
  onRaised: () => void;
}) {
  const [explanation, setExplanation] = useState("");
  const [error, setError] = useState<string | null>(null);

  const raiseMutation = useMutation({
    mutationFn: () =>
      api.raiseConclusionDiscrepancy(incidentId, runId, { explanation: explanation.trim() }),
    onMutate: () => setError(null),
    onSuccess: () => {
      setExplanation("");
      onRaised();
    },
    onError: (err) =>
      setError(err instanceof Error ? err.message : "Discrepancy could not be recorded."),
  });

  return (
    <form
      className="space-y-2 border-t border-slate-100 pt-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (explanation.trim()) {
          raiseMutation.mutate();
        }
      }}
    >
      <p className="label">{disputed ? "Flag another discrepancy" : "Flag a discrepancy"}</p>
      <p className="text-xs text-slate-500">
        Recording a discrepancy disputes this conclusion and returns the incident to
        unresolved review. The conclusion itself is immutable and is preserved for audit.
      </p>
      <textarea
        value={explanation}
        onChange={(event) => setExplanation(event.target.value)}
        rows={3}
        placeholder="Explain what is wrong with this conclusion."
        className="text-sm leading-relaxed"
      />
      {error && (
        <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={raiseMutation.isPending || !explanation.trim()}
        className="button-secondary"
      >
        {raiseMutation.isPending ? "Recording…" : "Flag discrepancy"}
      </button>
    </form>
  );
}

function CausalFactorGroup({
  label,
  factors,
  onFocusEvidence,
}: {
  label: string;
  factors: CausalFactor[];
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  return (
    <div className="space-y-2">
      <p className="label">{label}</p>
      <ul className="space-y-2">
        {factors.map((factor) => (
          <li key={factor.id} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-slate-900">{factor.title}</span>
              <ClaimSupportBadge status={factor.support_status} />
              {factor.challenge?.severity === "critical" && (
                <span className="badge bg-rose-50 text-rose-700 ring-rose-200">
                  critically challenged
                </span>
              )}
              {factor.advisory_rank !== null && (
                <span className="badge bg-slate-100 text-slate-600 ring-slate-200">
                  advisory rank {factor.advisory_rank}
                </span>
              )}
            </div>
            <p className="mt-1 text-sm leading-relaxed text-slate-700">{factor.summary}</p>
            {/* Partial-Support Acknowledgment kept visible so the uncertainty is never
                hidden (ADR 0042, PRD #26 stories 38-39). */}
            {factor.partial_support_acknowledgment && (
              <div className="mt-2 rounded-md border border-amber-200 bg-amber-50/70 px-2.5 py-1.5">
                <p className="text-xs font-medium text-amber-800">Partial support</p>
                <p className="mt-0.5 text-xs leading-relaxed text-amber-900">
                  {factor.partial_support_acknowledgment}
                </p>
              </div>
            )}
            {/* Preserve the actual critical challenge (challenged claim, counterclaims,
                evidence gaps, falsification tests) so the override can be audited
                against the concern it addresses (ADR 0042, PRD #26 story 41). */}
            {factor.challenge?.severity === "critical" && (
              <div className="mt-2">
                <ChallengePanel
                  challenge={factor.challenge}
                  onFocusEvidence={onFocusEvidence}
                />
              </div>
            )}
            {/* Critical-Challenge Override, shown with non-definitive wording — the
                unresolved challenge is acknowledged, not erased (stories 40-41). */}
            {factor.critical_challenge_override && (
              <div className="mt-2 rounded-md border border-rose-200 bg-rose-50/70 px-2.5 py-1.5">
                <p className="text-xs font-medium text-rose-800">
                  Critical challenge unresolved — included with override (not definitive)
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-rose-900">
                  {factor.critical_challenge_override}
                </p>
              </div>
            )}
            {factor.supporting_evidence.length > 0 && (
              <EvidenceRefList
                refs={factor.supporting_evidence}
                onFocusEvidence={onFocusEvidence}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Unevidenced reviewer beliefs, rendered separately from the evidence-backed
// factors and always labeled as assumptions so they never read as established fact
// (ADR 0042, PRD #26 story 38).
function HumanAssumptionList({ assumptions }: { assumptions: HumanAssumption[] }) {
  return (
    <div className="space-y-2">
      <p className="label flex items-center gap-2">
        Human assumptions
        <span className="badge bg-amber-50 text-amber-700 ring-amber-200">
          not evidence-backed
        </span>
      </p>
      <ul className="space-y-1.5">
        {assumptions.map((assumption) => (
          <li
            key={assumption.id}
            className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-sm leading-relaxed text-amber-900"
          >
            {assumption.statement}
          </li>
        ))}
      </ul>
    </div>
  );
}

function ConclusionForm({
  incidentId,
  runId,
  hypotheses,
  onFinalized,
  supersede,
  supersedeCandidates,
}: {
  incidentId: string;
  runId: string;
  hypotheses: Hypothesis[];
  onFinalized: () => void;
  // When present, the form always finalizes a Superseding Conclusion resolving the
  // named discrepancy on the predecessor (the same-run panel forces this) (ADR 0045).
  supersede?: { conclusionId: string; discrepancyId: string };
  // Disputed conclusions elsewhere in the incident this run may supersede instead of
  // finalizing an original — the new-Evidence path. Ignored when `supersede` is forced.
  supersedeCandidates?: RootCauseConclusion[];
}) {
  const [roles, setRoles] = useState<Record<string, CausalRole | "none">>({});
  const [acknowledgments, setAcknowledgments] = useState<Record<string, string>>({});
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState("");
  const [assumptionsText, setAssumptionsText] = useState("");
  const [error, setError] = useState<string | null>(null);
  // Cross-run supersede target chosen by the reviewer (empty = finalize an original).
  const [selectedPredecessorId, setSelectedPredecessorId] = useState("");

  const candidates = supersede === undefined ? (supersedeCandidates ?? []) : [];
  const selectedCandidate = candidates.find((c) => c.id === selectedPredecessorId) ?? null;
  // The effective supersede target: forced (same-run panel) or the chosen cross-run
  // predecessor, resolving the latest open discrepancy on it.
  const effectiveSupersede =
    supersede ??
    (selectedCandidate
      ? {
          conclusionId: selectedCandidate.id,
          discrepancyId:
            selectedCandidate.discrepancies[selectedCandidate.discrepancies.length - 1]?.id ?? "",
        }
      : undefined);

  const eligible = hypotheses.filter(hypothesisIsFinalizable);
  const byId = new Map(eligible.map((h) => [h.id, h]));

  // A partially supported factor needs a Partial-Support Acknowledgment; a
  // critically challenged failure mechanism needs a Critical-Challenge Override
  // (ADR 0042, PRD #26 stories 38-41). These mirror the backend trust floor so the
  // reviewer cannot submit an unqualified conclusion.
  const needsAcknowledgment = (h: Hypothesis) => h.support_status === "partial";
  const needsOverride = (h: Hypothesis, role: CausalRole | "none") =>
    role === "failure_mechanism" && h.challenge?.severity === "critical";

  const factors: CausalFactorInput[] = Object.entries(roles)
    .filter(([, role]) => role !== "none")
    .map(([hypothesis_id, role]) => {
      const hypothesis = byId.get(hypothesis_id);
      const input: CausalFactorInput = { hypothesis_id, role: role as CausalRole };
      if (hypothesis && needsAcknowledgment(hypothesis)) {
        input.partial_support_acknowledgment = (acknowledgments[hypothesis_id] ?? "").trim();
      }
      if (hypothesis && needsOverride(hypothesis, role)) {
        input.critical_challenge_override = (overrides[hypothesis_id] ?? "").trim();
      }
      return input;
    });
  const failureMechanismCount = factors.filter(
    (factor) => factor.role === "failure_mechanism",
  ).length;
  const humanAssumptions = assumptionsText
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const qualificationsComplete = factors.every((factor) => {
    const hypothesis = byId.get(factor.hypothesis_id);
    if (!hypothesis) return false;
    if (needsAcknowledgment(hypothesis) && !factor.partial_support_acknowledgment) {
      return false;
    }
    if (needsOverride(hypothesis, factor.role) && !factor.critical_challenge_override) {
      return false;
    }
    return true;
  });
  const isSupersede = effectiveSupersede !== undefined;
  const canFinalize =
    failureMechanismCount === 1 &&
    summary.trim().length > 0 &&
    qualificationsComplete &&
    // A chosen supersede target must carry a discrepancy to resolve.
    (!isSupersede || (effectiveSupersede?.discrepancyId ?? "").length > 0);

  const finalizeMutation = useMutation({
    mutationFn: () => {
      const base = {
        summary: summary.trim(),
        factors,
        human_assumptions: humanAssumptions,
      };
      if (effectiveSupersede) {
        return api.supersedeRunConclusion(incidentId, runId, {
          ...base,
          supersedes_conclusion_id: effectiveSupersede.conclusionId,
          discrepancy_id: effectiveSupersede.discrepancyId,
        });
      }
      return api.finalizeRunConclusion(incidentId, runId, base);
    },
    onMutate: () => setError(null),
    onSuccess: () => onFinalized(),
    onError: (err) =>
      setError(
        err instanceof Error
          ? err.message
          : isSupersede
            ? "Superseding conclusion could not be finalized."
            : "Conclusion could not be finalized.",
      ),
  });

  return (
    <div
      className={
        isSupersede
          ? "border-t border-violet-100 bg-violet-50/30"
          : "border-t border-slate-200 bg-slate-50/40"
      }
    >
      <div className="flex flex-wrap items-center gap-2 px-5 pt-3">
        <p
          className={`text-xs font-medium uppercase tracking-wide ${
            isSupersede ? "text-violet-700" : "text-slate-500"
          }`}
        >
          {isSupersede ? "Supersede this conclusion" : "Root Cause Conclusion"}
        </p>
        {!isSupersede && (
          <span className="badge bg-indigo-50 text-indigo-700 ring-indigo-200">
            not finalized
          </span>
        )}
      </div>
      <p className="px-5 pt-1 text-xs text-slate-500">
        {isSupersede
          ? "Resolve this dispute by finalizing a new conclusion from this run's accepted, evidence-backed hypotheses (reinterpretation of the same evidence). The disputed conclusion is preserved for audit; authority moves to the new one. For new evidence, start a new analysis run and supersede from there."
          : "Accepting a hypothesis keeps it as credible; it does not declare a root cause. Finalize a conclusion from the accepted, evidence-backed hypotheses below by assigning exactly one failure mechanism plus any triggers and amplifying conditions. A finalized conclusion is immutable."}
      </p>

      <div className="space-y-4 p-5">
        {candidates.length > 0 && (
          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-slate-700">Finalize as</span>
            <select
              value={selectedPredecessorId}
              onChange={(event) => setSelectedPredecessorId(event.target.value)}
              aria-label="Conclusion target"
            >
              <option value="">New root cause conclusion</option>
              {candidates.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  Supersede disputed conclusion (run {candidate.run_id.slice(0, 8)}):{" "}
                  {candidate.summary}
                </option>
              ))}
            </select>
            <p className="text-xs text-slate-500">
              This run can resolve a disputed conclusion from earlier in the incident by
              superseding it with this run&apos;s evidence, or finalize a fresh
              conclusion. Authority moves to the superseding conclusion; the disputed
              one is preserved for audit.
            </p>
          </label>
        )}
        {eligible.length === 0 ? (
          <p className="rounded-lg border border-dashed border-slate-300 bg-white/70 px-3 py-3 text-xs text-slate-500">
            No hypothesis is ready to finalize yet. Accept a hypothesis that has
            supported or partial evidence with verified citations first.
          </p>
        ) : (
          <ul className="space-y-2">
            {eligible.map((hypothesis) => {
              const role = roles[hypothesis.id] ?? "none";
              const showAcknowledgment = role !== "none" && needsAcknowledgment(hypothesis);
              const showOverride = needsOverride(hypothesis, role);
              const isCritical = hypothesis.challenge?.severity === "critical";
              return (
                <li
                  key={hypothesis.id}
                  className="space-y-2 rounded-lg border border-slate-200 bg-white px-3 py-2"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium text-slate-900">
                        {hypothesis.title}
                      </span>
                      <ClaimSupportBadge status={hypothesis.support_status} />
                      {isCritical && (
                        <span className="badge bg-rose-50 text-rose-700 ring-rose-200">
                          critically challenged
                        </span>
                      )}
                    </div>
                    <label className="flex items-center gap-2 text-xs text-slate-600">
                      <span>Role</span>
                      <select
                        value={role}
                        onChange={(event) =>
                          setRoles((current) => ({
                            ...current,
                            [hypothesis.id]: event.target.value as CausalRole | "none",
                          }))
                        }
                        aria-label={`Causal role for ${hypothesis.title}`}
                      >
                        {CAUSAL_ROLE_OPTIONS.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>

                  {showAcknowledgment && (
                    <label className="block space-y-1">
                      <span className="text-xs font-medium text-amber-700">
                        Partial-support acknowledgment (required)
                      </span>
                      <textarea
                        value={acknowledgments[hypothesis.id] ?? ""}
                        onChange={(event) =>
                          setAcknowledgments((current) => ({
                            ...current,
                            [hypothesis.id]: event.target.value,
                          }))
                        }
                        rows={2}
                        placeholder="Describe what the evidence supports and what remains uncertain."
                        aria-label={`Partial-support acknowledgment for ${hypothesis.title}`}
                        className="text-xs leading-relaxed"
                      />
                    </label>
                  )}

                  {showOverride && (
                    <label className="block space-y-1">
                      <span className="text-xs font-medium text-rose-700">
                        Critical-challenge override (required)
                      </span>
                      <p className="text-xs text-slate-500">
                        This hypothesis has an unresolved critical challenge. To use it as
                        the failure mechanism, address the challenge here. The challenge is
                        preserved and the conclusion stays non-definitive.
                      </p>
                      <textarea
                        value={overrides[hypothesis.id] ?? ""}
                        onChange={(event) =>
                          setOverrides((current) => ({
                            ...current,
                            [hypothesis.id]: event.target.value,
                          }))
                        }
                        rows={2}
                        placeholder="Explain why the critical challenge does not block this as the failure mechanism."
                        aria-label={`Critical-challenge override for ${hypothesis.title}`}
                        className="text-xs leading-relaxed"
                      />
                    </label>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-slate-700">Conclusion summary</span>
          <textarea
            value={summary}
            onChange={(event) => setSummary(event.target.value)}
            rows={3}
            placeholder="Summarize the causal account drawn from the factors above."
            className="text-sm leading-relaxed"
          />
        </label>

        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-slate-700">
            Human assumptions <span className="font-normal text-slate-400">(optional)</span>
          </span>
          <p className="text-xs text-slate-500">
            Unevidenced beliefs, one per line. These are recorded separately and labeled
            as assumptions — they never render as evidence-backed causal factors.
          </p>
          <textarea
            value={assumptionsText}
            onChange={(event) => setAssumptionsText(event.target.value)}
            rows={2}
            placeholder="One assumption per line."
            aria-label="Human assumptions"
            className="text-sm leading-relaxed"
          />
        </label>

        {failureMechanismCount > 1 && (
          <p className="text-xs text-amber-600">
            Choose exactly one failure mechanism.
          </p>
        )}
        {failureMechanismCount === 1 && !qualificationsComplete && (
          <p className="text-xs text-amber-600">
            Add the required partial-support acknowledgment or critical-challenge
            override for the factors above before finalizing.
          </p>
        )}
        {error && (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-700">
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={() => finalizeMutation.mutate()}
          disabled={!canFinalize || finalizeMutation.isPending}
          className="button-primary"
        >
          {finalizeMutation.isPending
            ? isSupersede
              ? "Superseding…"
              : "Finalizing…"
            : isSupersede
              ? "Finalize superseding conclusion"
              : "Finalize root cause conclusion"}
        </button>
      </div>
    </div>
  );
}

function EvidenceGroup({
  label,
  refs,
  onFocusEvidence,
}: {
  label: string;
  refs: EvidenceRef[];
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  return (
    <div className="space-y-1.5">
      <p className="label">{label}</p>
      <EvidenceRefList refs={refs} onFocusEvidence={onFocusEvidence} />
    </div>
  );
}

function EvidenceRefList({
  refs,
  onFocusEvidence,
}: {
  refs: EvidenceRef[];
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  return (
    <ul className="mt-1 space-y-1">
      {refs.map((ref) => (
        <li key={ref.id}>
          <button
            type="button"
            onClick={() => onFocusEvidence(ref)}
            className="block w-full rounded-sm text-left text-xs text-slate-500 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
          >
            <CitationStatusBadge status={ref.verifier_status} />{" "}
            <span className="font-medium text-slate-600">
              {ref.source_name}:{ref.line_start}
              {ref.line_end !== ref.line_start ? `-${ref.line_end}` : ""}
            </span>{" "}
            <CitationSnippet snippet={ref.snippet} />
          </button>
        </li>
      ))}
    </ul>
  );
}

function CitationSnippet({ snippet }: { snippet: string }) {
  return (
    <span className="whitespace-pre-wrap break-words font-mono text-slate-500">
      {snippet}
    </span>
  );
}

const CITATION_STATUS_LABEL: Record<EvidenceRef["verifier_status"], string> = {
  verified: "Citation verified — resolves to its exact immutable artifact lines",
  unverified: "Citation not yet verified",
  artifact_missing: "Broken citation — the cited artifact is missing",
  line_range_invalid: "Broken citation — the cited line range does not exist",
  snippet_mismatch: "Broken citation — the snippet no longer matches the cited lines",
};

function CitationStatusBadge({
  status,
}: {
  status: EvidenceRef["verifier_status"];
}) {
  const label = CITATION_STATUS_LABEL[status];
  if (status === "verified") {
    return (
      <svg
        className="inline-block shrink-0 text-emerald-600 align-[-1px]"
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        role="img"
        aria-label={label}
      >
        <title>{label}</title>
        <path d="M20 6 9 17l-5-5" />
      </svg>
    );
  }
  const tone =
    status === "unverified" ? "text-slate-400" : "text-rose-600";
  return (
    <svg
      className={`inline-block shrink-0 ${tone} align-[-1px]`}
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      strokeLinejoin="round"
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  );
}

function BulletGroup({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="space-y-1.5">
      <p className="label">{label}</p>
      <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

// The post-challenge Advisory Hypothesis Ranking rationale (ADR 0037). Shows WHY
// this hypothesis ranks where it does, across the five assessment dimensions, so
// the product visibly shows its work and ranking is never mistaken for a Root
// Cause Conclusion (PRD user stories 19, 88). Plausibility is ordinal and
// explained, never a probability (PRD user story 18).
const RANKING_DIMENSION_LABELS: Array<{ key: keyof RankingRationale; label: string }> = [
  { key: "support_strength", label: "Support strength" },
  { key: "counterevidence_severity", label: "Counterevidence severity" },
  { key: "explanatory_coverage", label: "Explanatory coverage" },
  { key: "evidence_gaps", label: "Evidence gaps" },
  { key: "assumption_dependence", label: "Assumption dependence" },
];

function RankingRationalePanel({
  rationale,
  advisoryRank,
  builderRank,
}: {
  rationale: RankingRationale;
  advisoryRank: number | null;
  builderRank: number;
}) {
  const reordered = advisoryRank !== null && advisoryRank !== builderRank;
  return (
    <div className="space-y-2 rounded-lg border border-indigo-100 bg-indigo-50/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <p className="label">Why this rank</p>
        {advisoryRank !== null && (
          <span className="badge bg-indigo-50 text-indigo-700 ring-indigo-200">
            advisory rank {advisoryRank}
          </span>
        )}
        {reordered && (
          <span
            className="text-xs text-slate-500"
            title="Falsification moved this candidate from its original generation order."
          >
            generated #{builderRank}
          </span>
        )}
      </div>
      <p className="text-sm leading-relaxed text-slate-700">{rationale.summary}</p>
      <dl className="grid gap-x-4 gap-y-1.5 sm:grid-cols-2">
        {RANKING_DIMENSION_LABELS.map(({ key, label }) => (
          <div key={key} className="text-xs">
            <dt className="font-medium text-slate-500">{label}</dt>
            <dd className="text-slate-700">{rationale[key]}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

// The bounded falsifier's challenge of one hypothesis (ADR 0034): severity, the
// challenged claim, cited counterclaims (navigable to exact evidence), and the
// procedural evidence gaps and falsification tests. This is how the Review
// Surface shows the analysis's work — contradicting evidence and critical
// challenges are visible without opening debug logs (PRD user stories 88-89).
function ChallengePanel({
  challenge,
  onFocusEvidence,
}: {
  challenge: HypothesisChallenge;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const critical = challenge.severity === "critical";
  return (
    <div
      className={`space-y-3 rounded-lg border p-3 ${
        critical ? "border-rose-200 bg-rose-50/50" : "border-slate-200 bg-slate-50/60"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="label">Falsification challenge</p>
        <ChallengeSeverityBadge severity={challenge.severity} />
      </div>
      <p className="text-sm leading-relaxed text-slate-700">{challenge.challenged_claim}</p>

      {challenge.counterclaims.length > 0 && (
        <div className="space-y-1.5">
          <p className="label">Counterclaims</p>
          <ul className="space-y-2">
            {challenge.counterclaims.map((counter) => (
              <li key={counter.id} className="text-sm text-slate-700">
                <span className="flex flex-wrap items-center gap-2">
                  <span>{counter.statement}</span>
                  {counter.assumption && (
                    <span className="badge bg-amber-50 text-amber-700 ring-amber-200">assumption</span>
                  )}
                </span>
                {counter.evidence_refs.length > 0 && (
                  <EvidenceRefList refs={counter.evidence_refs} onFocusEvidence={onFocusEvidence} />
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {challenge.evidence_gaps.length > 0 && (
        <BulletGroup label="Evidence gaps" items={challenge.evidence_gaps} />
      )}
      {challenge.falsification_tests.length > 0 && (
        <BulletGroup label="Falsification tests" items={challenge.falsification_tests} />
      )}
    </div>
  );
}

// Severity advises causal-role suitability (ADR 0034). A critical challenge, if
// valid, blocks the hypothesis from being the failure mechanism.
const CHALLENGE_SEVERITY_BADGE: Record<ChallengeSeverity, { label: string; cls: string }> = {
  critical: { label: "critical challenge", cls: "bg-rose-50 text-rose-700 ring-rose-200" },
  material: { label: "material challenge", cls: "bg-amber-50 text-amber-700 ring-amber-200" },
  minor: { label: "minor challenge", cls: "bg-slate-100 text-slate-600 ring-slate-200" },
};

function ChallengeSeverityBadge({ severity }: { severity: ChallengeSeverity }) {
  const config = CHALLENGE_SEVERITY_BADGE[severity];
  return <span className={`badge ${config.cls}`}>{config.label}</span>;
}

function ReviewStatusBadge({ status }: { status: HypothesisReviewStatus }) {
  const map: Record<HypothesisReviewStatus, string> = {
    proposed: "bg-slate-100 text-slate-600 ring-slate-200",
    accepted: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    rejected: "bg-rose-50 text-rose-700 ring-rose-200",
  };
  return <span className={`badge ${map[status]}`}>{status}</span>;
}

// The decision state of a Remediation Proposal (ADR 0041): generated 'proposed'
// until a human accepts, rejects, or defers it.
const REMEDIATION_STATUS_BADGE: Record<RemediationStatus, { label: string; cls: string }> = {
  proposed: { label: "proposed", cls: "bg-slate-100 text-slate-600 ring-slate-200" },
  accepted: { label: "accepted", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  rejected: { label: "rejected", cls: "bg-rose-50 text-rose-700 ring-rose-200" },
  deferred: { label: "deferred", cls: "bg-amber-50 text-amber-700 ring-amber-200" },
};

function RemediationStatusBadge({ status }: { status: RemediationStatus }) {
  const config = REMEDIATION_STATUS_BADGE[status];
  return <span className={`badge ${config.cls}`}>{config.label}</span>;
}

// Semantic claim-support verdict (ADR 0014). `unevaluated` shows nothing — the
// claim has not reached the flagging stage yet.
const CLAIM_SUPPORT_BADGE: Record<
  ClaimSupportStatus,
  { label: string; cls: string } | null
> = {
  unevaluated: null,
  supported: { label: "supported", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  partial: { label: "partial support", cls: "bg-amber-50 text-amber-700 ring-amber-200" },
  unsupported: { label: "unsupported", cls: "bg-rose-50 text-rose-700 ring-rose-200" },
};

function ClaimSupportBadge({ status }: { status: ClaimSupportStatus }) {
  const config = CLAIM_SUPPORT_BADGE[status];
  if (!config) {
    return null;
  }
  return <span className={`badge ${config.cls}`}>{config.label}</span>;
}

function SupportRationale({
  status,
  rationale,
}: {
  status: ClaimSupportStatus;
  rationale: string | null;
}) {
  // Caution context only matters when support is less than full (AC #3).
  if (!rationale || status === "supported" || status === "unevaluated") {
    return null;
  }
  const tone =
    status === "unsupported"
      ? "border-rose-200 bg-rose-50/60 text-rose-700"
      : "border-amber-200 bg-amber-50/60 text-amber-700";
  return (
    <p className={`mt-1.5 rounded-md border px-2.5 py-1.5 text-xs leading-relaxed ${tone}`}>
      {rationale}
    </p>
  );
}

function RunTimeline({
  incidentId,
  runId,
  onFocusEvidence,
}: {
  incidentId: string;
  runId: string;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  const timelineQuery = useQuery<TimelineEvent[]>({
    queryKey: ["run-timeline", incidentId, runId],
    queryFn: () => api.listRunTimeline(incidentId, runId),
  });

  if (timelineQuery.isPending) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        <Spinner /> Loading timeline…
      </div>
    );
  }

  if (timelineQuery.isError) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-rose-600">
        Timeline candidates could not be loaded.
      </div>
    );
  }

  const events = timelineQuery.data ?? [];
  if (events.length === 0) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        No timeline candidates: the included evidence had no recognizable timestamps.
      </div>
    );
  }

  return (
    <div className="border-t border-slate-200">
      <p className="px-5 pt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
        Timeline candidates · {events.length}
      </p>
      <ol className="divide-y divide-slate-100 px-2 py-1">
        {events.map((event) => (
          <li key={event.id} className="flex items-start gap-3 px-3 py-2.5">
            <span className="mt-0.5 w-40 shrink-0 text-xs tabular-nums text-slate-500">
              {event.normalized_ts
                ? new Date(event.normalized_ts).toISOString().replace(".000Z", "Z")
                : event.original_ts_text ?? "—"}
              {event.uncertain && (
                <span className="ml-1.5 badge bg-amber-50 text-amber-700 ring-amber-200">
                  inferred
                </span>
              )}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm text-slate-800">{event.description}</p>
              {event.evidence_refs.map((ref) => (
                <button
                  type="button"
                  key={ref.id}
                  onClick={() => onFocusEvidence(ref)}
                  className="mt-0.5 block w-full rounded-sm text-left text-xs text-slate-500 hover:text-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
                >
                  <CitationStatusBadge status={ref.verifier_status} />{" "}
                  <span className="font-medium text-slate-600">
                    {ref.source_name}:{ref.line_start}
                    {ref.line_end !== ref.line_start ? `-${ref.line_end}` : ""}
                  </span>{" "}
                  <CitationSnippet snippet={ref.snippet} />
                </button>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

function RunImpact({
  incidentId,
  runId,
  onFocusEvidence,
}: {
  incidentId: string;
  runId: string;
  onFocusEvidence: (ref: EvidenceRef) => void;
}) {
  // Impact is a run-level incident fact shown once, independent of how many RCA
  // hypotheses the run produced (ADR 0033 / PRD user stories 1-2).
  const impactQuery = useQuery<ImpactClaim[]>({
    queryKey: ["run-impact", incidentId, runId],
    queryFn: () => api.listRunImpactClaims(incidentId, runId),
  });

  if (impactQuery.isPending) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        <Spinner /> Loading impact…
      </div>
    );
  }

  if (impactQuery.isError) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-rose-600">
        Impact analysis could not be loaded.
      </div>
    );
  }

  const claims = impactQuery.data ?? [];
  if (claims.length === 0) {
    return (
      <div className="border-t border-slate-200 px-5 py-3 text-xs text-slate-500">
        No impact recorded: the included evidence showed no observed incident impact.
      </div>
    );
  }

  return (
    <div className="border-t border-slate-200">
      <p className="px-5 pt-3 text-xs font-medium uppercase tracking-wide text-slate-500">
        Impact · {claims.length}
      </p>
      <ul className="space-y-2 px-5 py-3">
        {claims.map((claim) => (
          <li key={claim.id} className="text-sm text-slate-700">
            <span className="flex flex-wrap items-center gap-2">
              <span>{claim.description}</span>
              {claim.assumption && (
                <span className="badge bg-amber-50 text-amber-700 ring-amber-200">
                  assumption
                </span>
              )}
              <ClaimSupportBadge status={claim.support_status} />
            </span>
            <SupportRationale
              status={claim.support_status}
              rationale={claim.support_rationale}
            />
            {claim.evidence_refs.length > 0 && (
              <EvidenceRefList
                refs={claim.evidence_refs}
                onFocusEvidence={onFocusEvidence}
              />
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// Human-readable labels for the controlled Causal Analysis Stage failure codes
// (ADR 0043). The raw code is still shown verbatim for an unmapped value so a new
// backend code never renders blank.
function failureCodeLabel(code: string): string {
  const map: Record<string, string> = {
    repair_exhausted: "Repair exhausted",
    budget_exhausted: "Reasoning budget exhausted",
    limit_exceeded: "Limit exceeded",
  };
  return map[code] ?? code;
}

function RunStatusBadge({ status }: { status: RunStatus }) {
  const map: Record<RunStatus, string> = {
    queued: "bg-slate-100 text-slate-600 ring-slate-200",
    running: "bg-amber-50 text-amber-700 ring-amber-200",
    succeeded: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    failed: "bg-rose-50 text-rose-700 ring-rose-200",
  };
  return <span className={`badge ${map[status]}`}>{status}</span>;
}

function StageStatusIcon({ status }: { status: StageStatus | undefined }) {
  if (status === "succeeded") {
    return (
      <svg className="text-emerald-600" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-label="succeeded">
        <path d="M20 6 9 17l-5-5" />
      </svg>
    );
  }
  if (status === "failed") {
    return (
      <svg className="text-rose-600" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-label="failed">
        <path d="M18 6 6 18" />
        <path d="m6 6 12 12" />
      </svg>
    );
  }
  if (status === "running") {
    return <Spinner />;
  }
  return <span className="inline-block h-2.5 w-2.5 rounded-full bg-slate-300" aria-label="pending" />;
}

function StageTiming({ event }: { event: RunStageEvent | undefined }) {
  if (!event) {
    return <>pending</>;
  }
  if (event.status === "running") {
    return <>running…</>;
  }
  // Both succeeded and failed terminal events carry a measured duration; show
  // it whenever it was recorded so observability is not lost on failure.
  if (event.duration_ms !== null) {
    return <>{event.duration_ms} ms</>;
  }
  return <>{event.status}</>;
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h2>
          {description && <p className="mt-0.5 text-sm text-slate-600">{description}</p>}
        </div>
      </div>
      {children}
    </section>
  );
}

function Spinner() {
  return (
    <svg
      className="animate-spin text-slate-500"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" />
      <path d="M22 12a10 10 0 0 1-10 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}
