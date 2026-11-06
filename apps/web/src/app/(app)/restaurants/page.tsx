import type { Metadata } from "next";

import { RestaurantsView } from "./view";

export const metadata: Metadata = { title: "Restaurantes" };

export default function Page() {
  return <RestaurantsView />;
}
