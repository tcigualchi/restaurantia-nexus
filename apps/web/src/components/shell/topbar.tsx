"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Clock, LogOut, Menu, Moon, Sun, X } from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";
import { useState } from "react";

import { Wordmark } from "@/components/brand";
import { PAUSE_REASON } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/input";
import { logout } from "@/lib/api";
import { clock } from "@/lib/format";

import { useApp } from "./app-context";
import { SidebarNav } from "./sidebar";

const ROLE_LABEL: Record<string, string> = { viewer: "Leitor", operator: "Operador", manager: "Gerente", owner: "Proprietário" };

export function Topbar() {
  const { restaurant, restaurants, setRestaurantId, live, me } = useApp();
  const { resolvedTheme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const sim = live.status?.simulation;

  return (
    <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur lg:px-6">
      <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
        <DialogPrimitive.Trigger asChild>
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Abrir menu">
            <Menu />
          </Button>
        </DialogPrimitive.Trigger>
        <DialogPrimitive.Portal>
          <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-black/40 lg:hidden" />
          <DialogPrimitive.Content className="fixed inset-y-0 left-0 z-50 flex w-72 flex-col bg-sidebar shadow-xl lg:hidden">
            <DialogPrimitive.Title className="sr-only">Menu</DialogPrimitive.Title>
            <div className="flex h-16 items-center justify-between border-b px-4">
              <Wordmark />
              <DialogPrimitive.Close asChild>
                <Button variant="ghost" size="icon" aria-label="Fechar menu">
                  <X />
                </Button>
              </DialogPrimitive.Close>
            </div>
            <SidebarNav onNavigate={() => setOpen(false)} />
          </DialogPrimitive.Content>
        </DialogPrimitive.Portal>
      </DialogPrimitive.Root>

      <label className="sr-only" htmlFor="restaurant-switcher">
        Restaurante
      </label>
      <Select
        id="restaurant-switcher"
        value={restaurant?.id ?? ""}
        onChange={(e) => setRestaurantId(e.target.value)}
        className="max-w-[16rem] font-medium"
      >
        {restaurants.map((r) => (
          <option key={r.id} value={r.id}>
            {r.name}
          </option>
        ))}
      </Select>
      {restaurant && <Badge tone="primary" className="hidden sm:inline-flex">{ROLE_LABEL[restaurant.role] ?? restaurant.role}</Badge>}

      <div className="ml-auto flex items-center gap-2">
        {sim && (
          <Link
            href="/simulation"
            className="hidden items-center gap-2 rounded-md border bg-card px-2.5 py-1.5 text-xs md:flex"
            title="Relógio da simulação (horário de São Paulo)"
          >
            <span className="rounded bg-warning-soft px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent-foreground">
              Simulação
            </span>
            <Clock className="size-3.5 text-muted-foreground" />
            <span className="font-mono tabular-nums">{clock(live.status?.business_time)}</span>
            <span className="text-muted-foreground">
              {sim.status === "paused" && sim.pause_reason ? `· ${PAUSE_REASON[sim.pause_reason] ?? "pausada"}` : sim.status === "running" ? "· rodando" : `· ${sim.status === "completed" ? "concluída" : "encerrada"}`}
            </span>
          </Link>
        )}
        {(live.status?.agents_running ?? 0) > 0 && (
          <Badge tone="info" className="hidden sm:inline-flex">
            Agentes analisando…
          </Badge>
        )}
        <Button
          variant="ghost"
          size="icon"
          aria-label="Alternar tema claro/escuro"
          onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
        >
          {resolvedTheme === "dark" ? <Sun /> : <Moon />}
        </Button>
        <Button variant="ghost" size="icon" aria-label={`Sair (${me?.display_name ?? ""})`} onClick={() => void logout()}>
          <LogOut />
        </Button>
      </div>
    </header>
  );
}
