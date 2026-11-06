import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/server-session";

interface ApiSession {
  access_token: string;
  expires_at: string;
  user: Record<string, unknown>;
  restaurants: unknown[];
}

/** Moves the access token into an httpOnly cookie; the body returned to the browser has no token. */
export function sessionResponse(session: ApiSession): NextResponse {
  const res = NextResponse.json({ user: session.user, restaurants: session.restaurants, expires_at: session.expires_at });
  res.cookies.set(SESSION_COOKIE, session.access_token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    expires: new Date(session.expires_at),
  });
  return res;
}
