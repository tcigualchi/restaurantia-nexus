"use client";

import { AppProvider } from "./app-context";
import { Sidebar } from "./sidebar";
import { Topbar } from "./topbar";

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AppProvider>
      <div className="flex min-h-dvh">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <main id="main" className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-6 lg:px-8">
            {children}
          </main>
        </div>
      </div>
    </AppProvider>
  );
}
