import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AppShell } from "@/components/shell/app-shell";
import { SESSION_COOKIE } from "@/lib/server-session";

// Optimistic check only: the API validates the token on every request.
export default async function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const store = await cookies();
  if (!store.get(SESSION_COOKIE)) redirect("/");
  return <AppShell>{children}</AppShell>;
}
