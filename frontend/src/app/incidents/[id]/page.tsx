"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChangeEvent, useEffect, useMemo, useState } from "react";
import {
  api,
  type AnalysisRun,
  type Artifact,
  type ArtifactSourceType,
  type Incident,
  type RunStatus,
} from "@/lib/api";
import { SeverityBadge, StatusBadge } from "../_components/badges";

const SOURCE_TYPES: Array<{ value: ArtifactSourceType; label: string }> = [
  { value: "incident_notes", label: "Incident notes" },
  { value: "logs", label: "Logs" },
  { value: "stack_trace", label: "Stack trace" },
  { value: "deployment_notes", label: "Deployment notes" },
  { value: "other", label: "Other" },
];

export default function IncidentOverviewPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [incident, setIncident] = useState<Incident | null>(null);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [runError, setRunError] = useState<Error | null>(null);
  const [isStartingRun, setIsStartingRun] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [artifactError, setArtifactError] = useState<Error | null>(null);
  const [isLoadingArtifacts, setIsLoadingArtifacts] = useState(false);

  useEffect(() => {
    if (!id) {
      return;
    }

    let active = true;
    setIsLoadingArtifacts(true);

    Promise.all([api.getIncident(id), api.listArtifacts(id), api.listAnalysisRuns(id)])
      .then(([incidentItem, artifactItems, runItems]) => {
        if (!active) {
          return;
        }
        setIncident(incidentItem);
        setArtifacts(artifactItems);
        setRuns(runItems);
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

  async function startRun() {
    if (!id) {
      return;
    }
    setRunError(null);
    setIsStartingRun(true);
    try {
      // Start the run, then fetch current status. Starting locks the included
      // evidence, so reload artifacts to reflect the lock without blocking.
      await api.startAnalysisRun(id);
      const [runItems] = await Promise.all([
        api.listAnalysisRuns(id),
        reloadArtifacts(selectedArtifactId),
      ]);
      setRuns(runItems);
    } catch (err) {
      setRunError(err instanceof Error ? err : new Error("Failed to start analysis run"));
    } finally {
      setIsStartingRun(false);
    }
  }

  async function refreshRuns() {
    if (!id) {
      return;
    }
    setRunError(null);
    try {
      setRuns(await api.listAnalysisRuns(id));
    } catch (err) {
      setRunError(err instanceof Error ? err : new Error("Failed to refresh runs"));
    }
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
          onSelect={setSelectedArtifactId}
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
          runs={runs}
          artifactCount={artifacts.length}
          isStarting={isStartingRun}
          error={runError}
          onStart={startRun}
          onRefresh={refreshRuns}
        />
      </Section>

      <Section title="Postmortem" description="Drafted from evidence with line-level citations.">
        <Placeholder
          tag="Coming in slices 6–9"
          body="Drafted postmortems with cited claims arrive in #7, #8, #9, #10."
        />
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
                <LineViewer artifact={selectedArtifact} />
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

function LineViewer({ artifact }: { artifact: Artifact }) {
  return (
    <div className="scroll-area max-h-[28rem] overflow-auto">
      <table className="w-full border-collapse font-mono text-[13px]">
        <tbody>
          {artifact.lines.map((line) => (
            <tr key={line.number} className="group border-b border-slate-100 last:border-b-0">
              <th
                scope="row"
                className="w-14 select-none border-r border-slate-200 bg-slate-50/70 px-3 py-1.5 text-right align-top text-xs font-normal text-slate-400 group-hover:text-slate-500"
              >
                {line.number}
              </th>
              <td className="whitespace-pre-wrap break-words px-4 py-1.5 align-top leading-6 text-slate-800 group-hover:bg-slate-50/40">
                {line.text || " "}
              </td>
            </tr>
          ))}
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
  runs,
  artifactCount,
  isStarting,
  error,
  onStart,
  onRefresh,
}: {
  runs: AnalysisRun[];
  artifactCount: number;
  isStarting: boolean;
  error: Error | null;
  onStart: () => Promise<void>;
  onRefresh: () => Promise<void>;
}) {
  const canStart = artifactCount > 0 && !isStarting;

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
              onClick={() => {
                void onRefresh();
              }}
              className="button-secondary"
            >
              Refresh status
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              void onStart();
            }}
            disabled={!canStart}
            className="button-primary"
          >
            {isStarting ? "Starting..." : "Start analysis run"}
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
        <ul className="card divide-y divide-slate-100 overflow-hidden">
          {runs.map((run) => (
            <li key={run.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3.5">
              <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-2">
                  <RunStatusBadge status={run.status} />
                  <span className="text-xs text-slate-500">
                    {run.artifact_ids.length} artifact
                    {run.artifact_ids.length === 1 ? "" : "s"} · {run.experiment_metadata.pipeline_version}
                  </span>
                </div>
                {run.error && <p className="text-xs text-rose-600">{run.error}</p>}
              </div>
              <span className="text-xs text-slate-500">
                Started {new Date(run.created_at).toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
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

function Placeholder({ tag, body }: { tag: string; body: string }) {
  return (
    <div className="card-padded flex flex-wrap items-center justify-between gap-3 border-dashed bg-white/60">
      <p className="text-sm text-slate-600">{body}</p>
      <span className="badge bg-slate-100 text-slate-600 ring-slate-200">{tag}</span>
    </div>
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
