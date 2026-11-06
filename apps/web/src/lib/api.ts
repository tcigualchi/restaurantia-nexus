"use client";

// Browser-side API client. Every call goes to the same-origin BFF proxy, which attaches
// the httpOnly session cookie as a bearer token. The browser never sees the token.
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: Record<string, unknown>,
  ) {
    super(message);
  }
}

async function parse<T>(res: Response): Promise<T> {
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = data?.error ?? {};
    if (res.status === 401 && typeof window !== "undefined") {
      hardNavigate("/?expired=1");
    }
    throw new ApiError(res.status, err.code ?? "http_error", err.message ?? `Erro ${res.status}`, err.details);
  }
  return data as T;
}

/** Full reload on purpose: drops every client-side cache that belonged to the old session. */
export function hardNavigate(url: string) {
  window.location.assign(url);
}

export async function logout() {
  await fetch("/api/session/logout", { method: "POST" });
  hardNavigate("/");
}

export const apiPath = (path: string) => `/api/proxy/${path.replace(/^\//, "")}`;

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return parse<T>(await fetch(apiPath(path), { cache: "no-store", signal }));
}

/** Fired after every successful mutation so the live feed polls right away instead of waiting. */
export const LIVE_POKE_EVENT = "nexus:live-poke";

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const result = await parse<T>(
    await fetch(apiPath(path), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? "{}" : JSON.stringify(body),
    }),
  );
  window.dispatchEvent(new Event(LIVE_POKE_EVENT));
  return result;
}

export const fetcher = <T,>(path: string) => apiGet<T>(path);
