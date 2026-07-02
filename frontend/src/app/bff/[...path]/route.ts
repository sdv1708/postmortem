// Backend-for-Frontend proxy: the browser calls this same-origin route with NO
// token; the server attaches the single-user bearer token and forwards to the
// FastAPI backend. This keeps the secret out of the shipped JS bundle — unlike a
// NEXT_PUBLIC_* value, which is inlined at build time and readable by anyone.
//
// Env is server-only (never NEXT_PUBLIC_):
//   POSTMORTEM_API_ORIGIN  — FastAPI base URL (e.g. http://localhost:8000)
//   POSTMORTEM_API_TOKEN   — the bearer secret; empty is allowed so the
//                            dev-bypass backend still works in e2e.

import { NextRequest } from "next/server";

// Never cache; run on Node so we can read process env and use fetch freely.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API_ORIGIN = (process.env.POSTMORTEM_API_ORIGIN ?? "http://localhost:8000").replace(
  /\/$/,
  "",
);
const API_TOKEN = process.env.POSTMORTEM_API_TOKEN ?? "";

// Cost-abuse backstop (NOT access control): a fixed-window per-IP limit on
// mutating requests, since those are what trigger LLM runs. In-memory, so it is
// per-instance and only meaningful on a single-instance deploy; a determined
// abuser across many IPs is not stopped. The real fix for that is a login gate.
const RATE_LIMIT_WINDOW_MS = 60_000;
const RATE_LIMIT_MAX_MUTATIONS = 30;
const rateBuckets = new Map<string, { count: number; resetAt: number }>();

function rateLimited(ip: string): boolean {
  const now = Date.now();
  const bucket = rateBuckets.get(ip);
  if (!bucket || now >= bucket.resetAt) {
    rateBuckets.set(ip, { count: 1, resetAt: now + RATE_LIMIT_WINDOW_MS });
    return false;
  }
  bucket.count += 1;
  return bucket.count > RATE_LIMIT_MAX_MUTATIONS;
}

function clientIp(req: NextRequest): string {
  const forwarded = req.headers.get("x-forwarded-for");
  if (forwarded) {
    return forwarded.split(",")[0]!.trim();
  }
  return req.headers.get("x-real-ip") ?? "unknown";
}

function jsonError(status: number, detail: string): Response {
  return new Response(JSON.stringify({ detail }), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function proxy(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const method = req.method.toUpperCase();

  // GETs are read-only and cheap; only meter the mutating, cost-bearing calls.
  if (method !== "GET" && rateLimited(clientIp(req))) {
    return jsonError(429, "rate limit exceeded, retry shortly");
  }

  const { path } = await ctx.params;
  const target = `${API_ORIGIN}/${path.join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  headers.set("content-type", "application/json");
  if (API_TOKEN) {
    headers.set("authorization", `Bearer ${API_TOKEN}`);
  }

  // GET/HEAD carry no body; everything else forwards the raw request body.
  const body = method === "GET" || method === "HEAD" ? undefined : await req.text();

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method,
      headers,
      body: body && body.length > 0 ? body : undefined,
      cache: "no-store",
    });
  } catch {
    return jsonError(502, "upstream backend unreachable");
  }

  // Pass the upstream response through verbatim — same status and body — so the
  // client's error parser still reads FastAPI's `detail`, and 204s stay empty.
  const outHeaders = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType) {
    outHeaders.set("content-type", contentType);
  }
  if (upstream.status === 204) {
    return new Response(null, { status: 204, headers: outHeaders });
  }
  const payload = await upstream.arrayBuffer();
  return new Response(payload, { status: upstream.status, headers: outHeaders });
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
export const PUT = proxy;
export const DELETE = proxy;
