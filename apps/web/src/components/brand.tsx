import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-8", className)}>
      <defs>
        <linearGradient id="nexus-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="oklch(0.62 0.12 183)" />
          <stop offset="100%" stopColor="oklch(0.5 0.13 250)" />
        </linearGradient>
      </defs>
      <path d="M16 2.5 28 9.25v13.5L16 29.5 4 22.75V9.25z" fill="url(#nexus-g)" />
      <g stroke="white" strokeWidth="1.6" strokeLinecap="round" fill="none" opacity="0.95">
        <path d="M16 9.5v13M10.5 12.75 21.5 19.25M21.5 12.75 10.5 19.25" />
      </g>
      <circle cx="16" cy="16" r="2.6" fill="white" />
    </svg>
  );
}

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {!compact && (
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight">
            RestaurantIA <span className="text-primary">Nexus</span>
          </div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-muted-foreground">Restaurant Intelligence</div>
        </div>
      )}
    </div>
  );
}
