import type { Metadata } from "next";

import { ApprovalsView } from "./view";

export const metadata: Metadata = { title: "Aprovações" };

export default function Page() {
  return <ApprovalsView />;
}
