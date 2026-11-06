"use client";

import { ThemeProvider } from "next-themes";
import { Toaster } from "sonner";
import { SWRConfig } from "swr";

import { TooltipProvider } from "@/components/ui/tooltip";
import { fetcher } from "@/lib/api";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <SWRConfig value={{ fetcher, revalidateOnFocus: true, dedupingInterval: 800, keepPreviousData: true }}>
        <TooltipProvider>
          {children}
          <Toaster richColors closeButton position="bottom-right" />
        </TooltipProvider>
      </SWRConfig>
    </ThemeProvider>
  );
}
