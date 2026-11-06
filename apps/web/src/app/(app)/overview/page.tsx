import type { Metadata } from "next";

import { OverviewView } from "./view";

export const metadata: Metadata = { title: "Visão geral" };

export default function Page() {
  return <OverviewView />;
}
