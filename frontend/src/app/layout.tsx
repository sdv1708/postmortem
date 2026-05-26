import type { Metadata } from "next";
import Link from "next/link";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Postmortem Agent",
  description: "Evidence-backed incident postmortems",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.className}>
      <body>
        <div className="flex min-h-screen flex-col">
          <header className="sticky top-0 z-30 border-b border-slate-200/70 bg-white/80 backdrop-blur supports-[backdrop-filter]:bg-white/60">
            <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3.5">
              <Link href="/" className="flex items-center gap-2.5 group">
                <span
                  aria-hidden
                  className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-slate-900 to-slate-700 text-white shadow-sm transition group-hover:shadow"
                >
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M12 3 4 7v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V7l-8-4Z" />
                    <path d="m9 12 2 2 4-4" />
                  </svg>
                </span>
                <span className="flex flex-col leading-tight">
                  <span className="text-sm font-semibold text-slate-900">Postmortem Agent</span>
                  <span className="text-[11px] text-slate-500">Evidence-backed reviews</span>
                </span>
              </Link>
              <nav className="flex items-center gap-1 text-sm">
                <Link
                  href="/incidents"
                  className="rounded-md px-3 py-1.5 font-medium text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
                >
                  Incidents
                </Link>
              </nav>
            </div>
          </header>

          <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-10">{children}</main>

          <footer className="border-t border-slate-200/70 bg-white/40">
            <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4 text-xs text-slate-500">
              <span>Postmortem Agent</span>
              <span>Slice 2 · Line-addressable evidence</span>
            </div>
          </footer>
        </div>
      </body>
    </html>
  );
}
