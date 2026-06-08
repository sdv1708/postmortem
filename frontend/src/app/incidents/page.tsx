"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Incident, type ScenarioSummary } from "@/lib/api";
import { SeverityBadge, StatusBadge } from "./_components/badges";

export default function IncidentsPage() {
  const router = useRouter();
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [seeding, setSeeding] = useState<string | null>(null);
  const [seedError, setSeedError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    api
      .listIncidents()
      .then((items) => {
        if (active) {
          setIncidents(items);
        }
      })
      .catch((err: Error) => {
        if (active) {
          setError(err);
        }
      });

    api
      .listScenarios()
      .then((items) => {
        if (active) {
          setScenarios(items);
        }
      })
      .catch(() => {
        // The demo-seed affordance is optional; ignore if scenarios can't load.
      });

    return () => {
      active = false;
    };
  }, []);

  async function seedScenario(scenarioId: string) {
    setSeeding(scenarioId);
    setSeedError(null);
    try {
      const result = await api.seedScenario(scenarioId);
      router.push(`/incidents/${result.incident_id}`);
    } catch (err) {
      setSeedError(err instanceof Error ? err.message : "Failed to seed the scenario");
      setSeeding(null);
    }
  }

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <p className="label">Workspace</p>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-900">Incidents</h1>
          <p className="text-sm text-slate-600">
            All recorded incidents across this workspace. Open one to attach evidence.
          </p>
        </div>
        <Link href="/incidents/new" className="button-primary">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14" />
            <path d="M5 12h14" />
          </svg>
          New incident
        </Link>
      </header>

      {scenarios.length > 0 && (
        <section className="card-padded border-indigo-200 bg-indigo-50/40">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="space-y-1">
              <p className="label">Demo</p>
              <h2 className="text-base font-semibold text-slate-900">Seed a synthetic incident</h2>
              <p className="max-w-prose text-sm text-slate-600">
                Load a realistic, file-based scenario with evidence and run the full
                analysis — multiple ranked hypotheses, exact citations, and an honest
                postmortem — without using real production logs.
              </p>
            </div>
          </div>
          {seedError && <p className="mt-3 text-sm text-rose-600">{seedError}</p>}
          <ul className="mt-4 grid gap-3 sm:grid-cols-2">
            {scenarios.map((scenario) => (
              <li
                key={scenario.id}
                className="flex flex-col gap-3 rounded-xl border border-indigo-200 bg-white p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <h3 className="text-sm font-semibold text-slate-900">{scenario.title}</h3>
                  {scenario.severity && <SeverityBadge severity={scenario.severity} />}
                </div>
                {scenario.ambiguity_notes && (
                  <p className="line-clamp-3 text-xs leading-relaxed text-slate-600">
                    {scenario.ambiguity_notes}
                  </p>
                )}
                <div className="mt-auto flex items-center justify-between gap-3">
                  <span className="text-xs text-slate-500">
                    {scenario.evidence_count} evidence files
                  </span>
                  <button
                    type="button"
                    className="button-secondary"
                    disabled={seeding !== null}
                    onClick={() => seedScenario(scenario.id)}
                  >
                    {seeding === scenario.id ? "Seeding…" : "Seed demo scenario"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {!incidents && !error && <ListSkeleton />}

      {error && (
        <div className="card-padded border-rose-200 bg-rose-50/40">
          <h3 className="text-sm font-semibold text-rose-700">Could not reach the backend</h3>
          <p className="mt-1 text-sm text-rose-600">
            Failed to load incidents. Is the backend running, and is your API token configured?
          </p>
        </div>
      )}

      {incidents && incidents.length === 0 && <EmptyState />}

      {incidents && incidents.length > 0 && (
        <ul className="grid gap-3 sm:grid-cols-2">
          {incidents.map((incident) => (
            <li key={incident.id}>
              <Link
                href={`/incidents/${incident.id}`}
                className="group flex h-full flex-col gap-3 rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-md focus:outline-none focus:ring-4 focus:ring-slate-900/10"
              >
                <div className="flex items-start justify-between gap-3">
                  <h2 className="line-clamp-2 text-base font-semibold text-slate-900 group-hover:text-indigo-700">
                    {incident.title}
                  </h2>
                  <SeverityBadge severity={incident.severity} />
                </div>
                {incident.summary && (
                  <p className="line-clamp-2 text-sm leading-relaxed text-slate-600">
                    {incident.summary}
                  </p>
                )}
                <div className="mt-auto flex items-center justify-between gap-3 text-xs text-slate-500">
                  <StatusBadge status={incident.status} />
                  <span>{formatRelative(incident.created_at)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ListSkeleton() {
  return (
    <ul className="grid gap-3 sm:grid-cols-2">
      {[0, 1, 2, 3].map((i) => (
        <li key={i} className="card-padded">
          <div className="h-4 w-2/3 animate-pulse rounded bg-slate-200" />
          <div className="mt-3 h-3 w-full animate-pulse rounded bg-slate-200" />
          <div className="mt-1.5 h-3 w-5/6 animate-pulse rounded bg-slate-200" />
          <div className="mt-4 flex justify-between">
            <div className="h-5 w-20 animate-pulse rounded-full bg-slate-200" />
            <div className="h-3 w-16 animate-pulse rounded bg-slate-200" />
          </div>
        </li>
      ))}
    </ul>
  );
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 bg-white/70 p-10 text-center">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-slate-100 text-slate-500">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M9 13h6" />
          <path d="M9 17h4" />
        </svg>
      </div>
      <h3 className="text-sm font-semibold text-slate-900">No incidents yet</h3>
      <p className="mt-1 text-sm text-slate-600">
        Create your first incident from the button above to start collecting evidence.
      </p>
    </div>
  );
}

function formatRelative(iso: string) {
  const date = new Date(iso);
  const diff = Date.now() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return date.toLocaleDateString();
}
