import Link from "next/link";

export default function Home() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Postmortem Agent</h1>
      <p className="text-neutral-600">
        Evidence-backed incident postmortems. Start by creating an incident.
      </p>
      <Link
        href="/incidents"
        className="inline-block rounded-md bg-neutral-900 px-4 py-2 text-sm text-white"
      >
        View incidents
      </Link>
    </div>
  );
}
