import type { Metadata } from "next";
import { Suspense } from "react";

import { ControlRoomView } from "./view";

export const metadata: Metadata = { title: "Agentes" };

export default function Page() {
  return (
    <Suspense>
      <ControlRoomView />
    </Suspense>
  );
}
