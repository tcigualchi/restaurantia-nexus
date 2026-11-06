import type { Metadata } from "next";

import { ForecastingView } from "./view";

export const metadata: Metadata = { title: "Previsão de demanda" };

export default function Page() {
  return <ForecastingView />;
}
