"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, type Severity } from "@/lib/api";

const SEVERITIES = ["sev0", "sev1", "sev2", "sev3", "sev4"] as const;

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
    <div className="max-w-xl space-y-6">
      <h1 className="text-2xl font-semibold">New incident</h1>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label className="block space-y-1">
          <span className="text-sm font-medium">Title</span>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            className="w-full rounded-md border px-3 py-2 text-sm"
            placeholder="API 500s spiking after 14:28 deploy"
          />
        </label>

        <label className="block space-y-1">
          <span className="text-sm font-medium">Severity</span>
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as Severity | "")}
            className="w-full rounded-md border px-3 py-2 text-sm"
          >
            <option value="">unspecified</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-1">
          <span className="text-sm font-medium">Summary</span>
          <textarea
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={4}
            className="w-full rounded-md border px-3 py-2 text-sm"
            placeholder="Short description of the incident."
          />
        </label>

        {error && <p className="text-sm text-red-600">{error.message}</p>}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={isSubmitting || !title.trim()}
            className="button-primary"
          >
            {isSubmitting ? "Creating..." : "Create incident"}
          </button>
          <button
            type="button"
            onClick={() => router.back()}
            className="button-secondary"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
