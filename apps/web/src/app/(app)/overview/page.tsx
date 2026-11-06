import type { Metadata } from "next";

import { OverviewView } from "./view";

export const metadata: Metadata = { title: "Overview" };

export default function Page() {
  return <OverviewView />;
}
