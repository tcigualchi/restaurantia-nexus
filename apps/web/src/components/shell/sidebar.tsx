"use client";

import {
  Activity,
  BookOpen,
  Bot,
  Boxes,
  ClipboardCheck,
  FlaskConical,
  LayoutDashboard,
  LineChart,
  ReceiptText,
  ScrollText,
  Settings,
  Store,
  TestTubes,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Wordmark } from "@/components/brand";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { useApp } from "./app-context";

const NAV = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard },
  { href: "/restaurants", label: "Restaurantes", icon: Store },
  { href: "/orders", label: "Pedidos", icon: ReceiptText },
  { href: "/inventory", label: "Estoque", icon: Boxes },
  { href: "/simulation", label: "Simulation Lab", icon: FlaskConical },
  { href: "/control-room", label: "AI Control Room", icon: Bot },
  { href: "/approvals", label: "Approval Center", icon: ClipboardCheck, badge: "approvals" as const },
  { href: "/forecasting", label: "Forecasting", icon: LineChart },
  { href: "/audit", label: "Audit Log", icon: ScrollText },
  { href: "/settings", label: "Configurações", icon: Settings },
];

const ROADMAP = [
  { label: "Knowledge Base (RAG)", icon: BookOpen, phase: "Fase 3" },
  { label: "Evaluation Lab", icon: TestTubes, phase: "Fase 4" },
];

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { live } = useApp();
  const pending = live.status?.pending_approvals ?? 0;
  return (
    <nav aria-label="Navegação principal" className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-3 py-2">
      {NAV.map(({ href, label, icon: Icon, badge }) => {
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
              active && "bg-card font-medium text-foreground shadow-sm ring-1 ring-border",
            )}
          >
            <Icon className="size-4" />
            <span className="flex-1">{label}</span>
            {badge === "approvals" && pending > 0 && (
              <span className="rounded-full bg-warning px-1.5 text-[11px] font-semibold text-black">{pending}</span>
            )}
          </Link>
        );
      })}
      <div className="mt-4 px-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Roadmap
      </div>
      {ROADMAP.map(({ label, icon: Icon, phase }) => (
        <div
          key={label}
          aria-disabled="true"
          title="Ainda não implementado — veja docs/roadmap.md"
          className="flex cursor-not-allowed items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted-foreground/60"
        >
          <Icon className="size-4" />
          <span className="flex-1">{label}</span>
          <Badge tone="neutral">{phase}</Badge>
        </div>
      ))}
    </nav>
  );
}

export function Sidebar() {
  const { live } = useApp();
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r bg-sidebar lg:flex">
      <div className="flex h-16 items-center border-b px-5">
        <Link href="/overview" aria-label="RestaurantIA Nexus — Overview">
          <Wordmark />
        </Link>
      </div>
      <SidebarNav />
      <div className="border-t px-5 py-3 text-[11px] text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <Activity className={cn("size-3", live.connected ? "text-success" : "text-muted-foreground")} />
          {live.connected ? "Atualização em tempo real" : "Reconectando…"}
        </div>
      </div>
    </aside>
  );
}
