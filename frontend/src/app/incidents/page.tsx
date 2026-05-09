"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

export default function IncidentsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["incidents"],
    queryFn: api.listIncidents,
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Incidents</h1>
        <Link
          href="/incidents/new"
          className="rounded-md bg-neutral-900 px-3 py-2 text-sm text-white"
        >
          New incident
        </Link>
      </div>

      {isLoading && <p className="text-sm text-neutral-500">Loading…</p>}
      {error && (
        <p className="text-sm text-red-600">
          Failed to load incidents. Is the backend running and is your API token set?
        </p>
      )}
      {data && data.length === 0 && (
        <p className="text-sm text-neutral-500">No incidents yet. Create one to get started.</p>
      )}
      {data && data.length > 0 && (
        <ul className="divide-y rounded-md border bg-white">
          {data.map((incident) => (
            <li key={incident.id} className="p-4">
              <Link href={`/incidents/${incident.id}`} className="block space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{incident.title}</span>
                  <span className="text-xs uppercase tracking-wide text-neutral-500">
                    {incident.severity ?? "unspecified"} · {incident.status}
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
