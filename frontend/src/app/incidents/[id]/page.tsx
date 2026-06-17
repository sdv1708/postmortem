"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChangeEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  isTerminalRunStatus,
  RUN_STAGES,
  type AnalysisRun,
  type Artifact,
  type ArtifactSourceType,
  type ClaimSupportStatus,
  type EvidenceRef,
  type ExportMode,
  type Hypothesis,
  type HypothesisReviewStatus,
  type ImpactClaim,
  type Incident,
  type Postmortem,
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
        <p className="border-b border-rose-100 bg-rose-50/60 px-5 py-2 text-xs text-rose-700">
          {run.error}
        </p>
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
        <RunPostmortem incidentId={incidentId} runId={run.id} />
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

  return (
    <div className="border-t border-slate-200 bg-slate-50/40">
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 pt-3">
        <div className="flex items-center gap-2">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Postmortem</p>
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
          <span className="mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-100 text-xs font-semibold tabular-nums text-slate-600">
            {hypothesis.rank}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="text-sm font-semibold text-slate-900">{hypothesis.title}</h4>
              {hypothesis.assumption && (
                <span className="badge bg-amber-50 text-amber-700 ring-amber-200">assumption</span>
              )}
              <ClaimSupportBadge status={hypothesis.support_status} />
              <ReviewStatusBadge status={hypothesis.review_status} />
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

        {hypothesis.action_items.length > 0 && (
          <div className="space-y-1.5">
            <p className="label">Remediation</p>
            <ul className="space-y-2">
              {hypothesis.action_items.map((item) => (
                <li key={item.id} className="text-sm text-slate-700">
                  <span>{item.description}</span>
                  {item.evidence_refs.length > 0 && (
                    <EvidenceRefList
                      refs={item.evidence_refs}
                      onFocusEvidence={onFocusEvidence}
                    />
                  )}
                </li>
              ))}
            </ul>
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

function ReviewStatusBadge({ status }: { status: HypothesisReviewStatus }) {
  const map: Record<HypothesisReviewStatus, string> = {
    proposed: "bg-slate-100 text-slate-600 ring-slate-200",
    accepted: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    rejected: "bg-rose-50 text-rose-700 ring-rose-200",
  };
  return <span className={`badge ${map[status]}`}>{status}</span>;
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
