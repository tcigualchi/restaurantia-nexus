import { API_URL, forwardedHeaders } from "@/lib/server-session";

import { sessionResponse } from "../session-cookie";

export const dynamic = "force-dynamic";

export async function POST(req: Request): Promise<Response> {
  const body = await req.json().catch(() => ({}));
  let upstream: Response;
  try {
    upstream = await fetch(`${API_URL}/api/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...forwardedHeaders(req) },
      body: JSON.stringify({ email: String(body?.email ?? ""), password: String(body?.password ?? "") }),
      cache: "no-store",
    });
  } catch {
    return Response.json({ error: { code: "api_unreachable", message: "API indisponível." } }, { status: 502 });
  }
  const data = await upstream.json().catch(() => ({}));
  if (!upstream.ok) return Response.json(data, { status: upstream.status });
  return sessionResponse(data);
}
