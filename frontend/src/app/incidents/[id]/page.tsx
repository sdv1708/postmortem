"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Incident } from "@/lib/api";

export default function IncidentOverviewPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const [incident, setIncident] = useState<Incident | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    if (!id) {
      return;
    }

    let active = true;

    api
      .getIncident(id)
      .then((item) => {
        if (active) {
          setIncident(item);
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
  }, [id]);

  if (!incident && !error) {
    return <p className="text-sm text-neutral-500">Loading...</p>;
  }

  if (error) {
    return <p className="text-sm text-red-600">Failed to load incident.</p>;
  }

  if (!incident) {
    return null;
  }

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <Link href="/incidents" className="text-sm text-neutral-500">
          Back to all incidents
        </Link>
        <h1 className="text-2xl font-semibold">{incident.title}</h1>
        <p className="text-sm text-neutral-600">
          {incident.severity ?? "unspecified"} / {incident.status} / created{" "}
          {new Date(incident.created_at).toLocaleString()}
        </p>
        {incident.summary && <p className="text-sm leading-relaxed">{incident.summary}</p>}
      </div>

      <Section title="Evidence">
        <Placeholder>Evidence upload will land in slice 2 (#3).</Placeholder>
      </Section>

      <Section title="Analysis runs">
        <Placeholder>Async runs and the six-stage status page land in slices 3-4 (#4, #5).</Placeholder>
      </Section>

      <Section title="Postmortem">
        <Placeholder>
          Drafted postmortems with cited claims arrive in slices 6-9 (#7, #8, #9, #10).
        </Placeholder>
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      {children}
    </section>
  );
}

function Placeholder({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed bg-white p-4 text-sm text-neutral-500">
      {children}
    </div>
  );
}
