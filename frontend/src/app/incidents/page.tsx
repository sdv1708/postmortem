"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Incident } from "@/lib/api";

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[] | null>(null);
  const [error, setError] = useState<Error | null>(null);

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

    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Incidents</h1>
        <Link
          href="/incidents/new"
          className="button-primary"
        >
          New incident
        </Link>
      </div>

      {!incidents && !error && <p className="text-sm text-neutral-500">Loading...</p>}
      {error && (
        <p className="text-sm text-red-600">
          Failed to load incidents. Is the backend running and is your API token set?
        </p>
      )}
      {incidents && incidents.length === 0 && (
        <p className="text-sm text-neutral-500">No incidents yet. Create one to get started.</p>
      )}
      {incidents && incidents.length > 0 && (
        <ul className="divide-y rounded-md border bg-white">
          {incidents.map((incident) => (
            <li key={incident.id} className="p-4">
              <Link href={`/incidents/${incident.id}`} className="block space-y-1">
                <div className="flex items-center justify-between gap-4">
                  <span className="font-medium">{incident.title}</span>
                  <span className="shrink-0 text-xs uppercase tracking-wide text-neutral-500">
                    {incident.severity ?? "unspecified"} / {incident.status}
                  </span>
                </div>
                {incident.summary && (
                  <p className="text-sm text-neutral-600 line-clamp-2">{incident.summary}</p>
                )}
                <p className="text-xs text-neutral-500">
                  Created {new Date(incident.created_at).toLocaleString()}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
