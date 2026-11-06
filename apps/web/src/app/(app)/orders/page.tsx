import type { Metadata } from "next";

import { OrdersView } from "./view";

export const metadata: Metadata = { title: "Pedidos" };

export default function Page() {
  return <OrdersView />;
}
