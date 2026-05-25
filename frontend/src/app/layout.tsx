import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Postmortem Agent",
  description: "Evidence-backed incident postmortems",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen">
          <header className="border-b bg-white">
            <div className="mx-auto max-w-5xl px-6 py-4 flex items-center justify-between">
              <Link href="/" className="font-semibold">
                Postmortem Agent
              </Link>
              <nav className="text-sm text-neutral-600 flex gap-4">
                <Link href="/incidents">Incidents</Link>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
