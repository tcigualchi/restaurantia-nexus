import type { NextRequest } from "next/server";

import { API_URL, SESSION_COOKIE, forwardedHeaders } from "@/lib/server-session";

// Backend-for-frontend proxy: the browser calls /api/proxy/v1/...; this handler forwards
// to the FastAPI service with the session token from an httpOnly cookie. Only /api/v1/*
// paths are reachable, request headers are allow-listed and SSE responses are streamed.
export const dynamic = "force-dynamic";
// SSE responses are long-lived; the API closes streams after 240 s and the browser reconnects.
export const maxDuration = 300;

const ALLOWED_REQUEST_HEADERS = ["content-type", "accept", "last-event-id"];
const ALLOWED_RESPONSE_HEADERS = ["content-type", "cache-control", "retry-after", "x-request-id"];

async function handler(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const { path } = await ctx.params;
  if (path[0] !== "v1" || path.some((p) => p === ".." || p.includes("\\"))) {
    return Response.json({ error: { code: "not_found", message: "Rota inválida." } }, { status: 404 });
  }
  const target = new URL(`${API_URL}/api/${path.map(encodeURIComponent).join("/")}`);
  req.nextUrl.searchParams.forEach((value, key) => target.searchParams.append(key, value));

  const headers: Record<string, string> = forwardedHeaders(req);
  for (const name of ALLOWED_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers[name] = value;
  }
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: req.method,
      headers,
      body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(),
      cache: "no-store",
      signal: req.signal,
    });
  } catch {
    return Response.json(
      { error: { code: "api_unreachable", message: "API indisponível no momento. Tente novamente." } },
      { status: 502 },
    );
  }
  const responseHeaders = new Headers();
  for (const name of ALLOWED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  if ((upstream.headers.get("content-type") ?? "").startsWith("text/event-stream")) {
    responseHeaders.set("X-Accel-Buffering", "no");
    responseHeaders.set("Cache-Control", "no-cache, no-transform");
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export { handler as GET, handler as POST };
