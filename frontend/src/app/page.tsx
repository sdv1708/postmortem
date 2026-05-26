import Link from "next/link";

export default function Home() {
  return (
    <div className="relative">
      <div className="grid gap-10 lg:grid-cols-[1.1fr_1fr] lg:items-center">
        <div className="space-y-6">
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 shadow-sm">
            <span className="h-1.5 w-1.5 rounded-full bg-indigo-500" />
            Slice 2 · Evidence management
          </span>
          <h1 className="text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
            Postmortems with evidence,{" "}
            <span className="bg-gradient-to-r from-indigo-600 to-sky-500 bg-clip-text text-transparent">
              line by line.
            </span>
          </h1>
          <p className="max-w-xl text-base leading-relaxed text-slate-600">
            Capture incidents, attach line-addressable logs and notes, and let the agent draft a
            cited postmortem you can trust.
          </p>
          <div className="flex flex-wrap items-center gap-3 pt-2">
            <Link href="/incidents" className="button-primary">
              View incidents
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14" />
                <path d="m13 5 7 7-7 7" />
              </svg>
            </Link>
            <Link href="/incidents/new" className="button-secondary">
              New incident
            </Link>
          </div>
        </div>

        <div className="relative">
          <div className="absolute -inset-4 -z-10 rounded-2xl bg-gradient-to-br from-indigo-500/10 via-sky-400/5 to-transparent blur-2xl" />
          <div className="card overflow-hidden">
            <div className="flex items-center gap-2 border-b border-slate-200 bg-slate-50/60 px-4 py-2.5">
              <span className="h-2.5 w-2.5 rounded-full bg-rose-300" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber-300" />
              <span className="h-2.5 w-2.5 rounded-full bg-emerald-300" />
              <span className="ml-2 text-xs text-slate-500">api-errors.log</span>
            </div>
            <div className="grid grid-cols-[3rem_1fr] font-mono text-[13px] leading-6">
              {[
                "14:28  deploy v184 started",
                "14:31  rolling restart of api-* pods",
                "14:32  500s spike to 12% of req",
                "14:34  rollback initiated",
                "14:37  error rate back to baseline",
              ].map((line, idx) => (
                <div key={idx} className="contents">
                  <span className="select-none border-r border-slate-200 bg-slate-50/60 px-3 py-1 text-right text-xs text-slate-400">
                    {idx + 1}
                  </span>
                  <span
                    className={`px-4 py-1 ${
                      idx === 2 ? "bg-rose-50 text-rose-700" : "text-slate-700"
                    }`}
                  >
                    {line}
                  </span>
                </div>
              ))}
            </div>
            <div className="border-t border-slate-200 bg-slate-50/60 px-4 py-2.5 text-xs text-slate-500">
              Cited in postmortem: <span className="text-slate-700">L3 · 500s spike</span>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-16 grid gap-4 sm:grid-cols-3">
        {[
          { title: "Capture", body: "Log incidents with severity and a quick summary." },
          { title: "Attach", body: "Drop logs, notes, traces. Each line gets a permanent address." },
          { title: "Cite", body: "Draft postmortems with claims tied back to source lines." },
        ].map((item) => (
          <div key={item.title} className="card-padded">
            <h3 className="text-sm font-semibold text-slate-900">{item.title}</h3>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-600">{item.body}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
