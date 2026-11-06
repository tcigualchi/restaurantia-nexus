import type { Metadata } from "next";

import { SimulationView } from "./view";

export const metadata: Metadata = { title: "Simulation Lab" };

export default function Page() {
  return <SimulationView />;
}
