"use client";

import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

export function JsonView({ value, label, defaultOpen = false }: { value: unknown; label: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  if (value == null) return null;
  const text = JSON.stringify(value, null, 2);
  return (
    <div className="rounded-md border bg-muted/40">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-left text-xs font-medium text-muted-foreground hover:text-foreground cursor-pointer"
      >
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        {label}
        <span className="ml-auto font-mono text-[10px] opacity-70">{(text.length / 1024).toFixed(1)} KB</span>
      </button>
      {open && (
        <pre className="max-h-80 overflow-auto border-t px-3 py-2 font-mono text-[11px] leading-relaxed">{text}</pre>
      )}
    </div>
  );
}
