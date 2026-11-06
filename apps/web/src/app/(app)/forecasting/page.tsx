import type { Metadata } from "next";

import { ForecastingView } from "./view";

export const metadata: Metadata = { title: "Forecasting" };

export default function Page() {
  return <ForecastingView />;
}
