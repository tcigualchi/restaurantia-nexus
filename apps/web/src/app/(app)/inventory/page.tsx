import type { Metadata } from "next";

import { InventoryView } from "./view";

export const metadata: Metadata = { title: "Estoque" };

export default function Page() {
  return <InventoryView />;
}
