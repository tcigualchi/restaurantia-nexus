import "server-only";

export const SESSION_COOKIE = "nexus_session";
export const API_URL = (process.env.API_INTERNAL_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Headers that let the API attribute rate limits to the real client behind this BFF. */
export function forwardedHeaders(req: Request): Record<string, string> {
  const headers: Record<string, string> = {};
  const secret = process.env.PROXY_SHARED_SECRET;
  const forwarded = req.headers.get("x-forwarded-for") ?? req.headers.get("x-real-ip") ?? "";
  const clientIp = forwarded.split(",")[0]?.trim();
  if (secret && clientIp) {
    headers["X-Proxy-Secret"] = secret;
    headers["X-Client-IP"] = clientIp;
  }
  const requestId = req.headers.get("x-request-id");
  if (requestId) headers["X-Request-ID"] = requestId;
  return headers;
}
