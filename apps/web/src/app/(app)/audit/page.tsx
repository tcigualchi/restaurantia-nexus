import type { Metadata } from "next";

import { AuditView } from "./view";

export const metadata: Metadata = { title: "Auditoria" };

export default function Page() {
  return <AuditView />;
}
