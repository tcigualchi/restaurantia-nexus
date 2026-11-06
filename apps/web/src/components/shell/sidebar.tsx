"use client";

import {
  Activity,
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
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { Wordmark } from "@/components/brand";
import { cn } from "@/lib/utils";

import { useApp } from "./app-context";

const NAV = [
  { href: "/overview", label: "Visão geral", icon: LayoutDashboard },
  { href: "/simulation", label: "Simulação", icon: FlaskConical },
  { href: "/control-room", label: "Agentes", icon: Bot },
  { href: "/approvals", label: "Aprovações", icon: ClipboardCheck, badge: "approvals" as const },
  { href: "/orders", label: "Pedidos", icon: ReceiptText },
  { href: "/inventory", label: "Estoque", icon: Boxes },
  { href: "/forecasting", label: "Previsão", icon: LineChart },
  { href: "/audit", label: "Auditoria", icon: ScrollText },
  { href: "/restaurants", label: "Restaurantes", icon: Store },
  { href: "/settings", label: "Configurações", icon: Settings },
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
    </nav>
  );
}

export function Sidebar() {
  const { live } = useApp();
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r bg-sidebar lg:flex">
      <div className="flex h-16 items-center border-b px-5">
        <Link href="/overview" aria-label="RestaurantIA Nexus, visão geral">
          <Wordmark />
        </Link>
      </div>
      <SidebarNav />
      <div className="border-t px-5 py-3 text-[11px] text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <Activity className={cn("size-3", live.connected ? "text-success" : "text-muted-foreground")} />
          {live.connected ? "Dados ao vivo" : "Reconectando…"}
        </div>
      </div>
    </aside>
  );
}
