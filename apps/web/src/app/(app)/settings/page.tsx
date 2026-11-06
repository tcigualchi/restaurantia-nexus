import type { Metadata } from "next";

import { SettingsView } from "./view";

export const metadata: Metadata = { title: "Configurações" };

export default function Page() {
  return <SettingsView />;
}
