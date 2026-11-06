import type { Metadata } from "next";

import { SimulationView } from "./view";

export const metadata: Metadata = { title: "Simulação" };

export default function Page() {
  return <SimulationView />;
}
