import { NextResponse } from "next/server";

import { SESSION_COOKIE } from "@/lib/server-session";

export async function POST(): Promise<Response> {
  const res = NextResponse.json({ ok: true });
  res.cookies.delete(SESSION_COOKIE);
  return res;
}
