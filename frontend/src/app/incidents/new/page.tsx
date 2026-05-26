"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, type Severity } from "@/lib/api";

const SEVERITIES: Array<{ value: Severity; label: string; hint: string }> = [
  { value: "sev0", label: "sev0", hint: "Critical · full outage" },
  { value: "sev1", label: "sev1", hint: "Major · core feature down" },
  { value: "sev2", label: "sev2", hint: "Significant degradation" },
  { value: "sev3", label: "sev3", hint: "Minor · limited impact" },
  { value: "sev4", label: "sev4", hint: "Trivial · cosmetic" },
];

export default function NewIncidentPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [severity, setSeverity] = useState<Severity | "">("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  async function submit() {
    setIsSubmitting(true);
    setError(null);

    try {
      const incident = await api.createIncident({
        title,
        summary: summary || null,
        severity: severity || null,
      });
      router.push(`/incidents/${incident.id}`);
    } catch (err) {
      setError(err instanceof Error ? err : new Error("Failed to create incident"));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div className="space-y-2">
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
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900">New incident</h1>
        <p className="text-sm text-slate-600">
          Record the basics now — you can attach evidence right after.
        </p>
      </div>

      <form
        className="card-padded space-y-6"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-slate-700">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            placeholder="API 500s spiking after 14:28 deploy"
          />
          <span className="block text-xs text-slate-500">A short, scannable headline.</span>
        </label>

        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-slate-700">Severity</span>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as Severity | "")}
          >
            <option value="">unspecified</option>
            {SEVERITIES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label} — {s.hint}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1.5">
          <span className="text-sm font-medium text-slate-700">Summary</span>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={5}
            placeholder="Short description of the incident."
          />
          <span className="block text-xs text-slate-500">Optional — a few sentences of context.</span>
        </label>

        {error && (
          <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
            {error.message}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 pt-5">
          <button
            type="submit"
            disabled={isSubmitting || !title.trim()}
            className="button-primary"
          >
            {isSubmitting ? "Creating..." : "Create incident"}
          </button>
          <Link href="/incidents" className="button-secondary">
            Cancel
          </Link>
        </div>
      </form>
    </div>
  );
}
