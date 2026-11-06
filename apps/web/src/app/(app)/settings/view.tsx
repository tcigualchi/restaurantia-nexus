"use client";

import { LogOut, Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import useSWR from "swr";

import { useApp } from "@/components/shell/app-context";
import { PageHeader } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { logout } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { SystemInfo } from "@/lib/types";

const PERMISSION_LABEL: Record<string, string> = {
  view: "Visualizar dados do restaurante",
  "simulation.control": "Controlar a simulação",
  "events.ingest": "Enviar eventos pela API",
  "agents.run": "Solicitar análises dos agentes",
  "approvals.decide": "Aprovar ou rejeitar ações sensíveis",
  "menu.update": "Pausar e reativar itens do cardápio",
  "sandbox.reset": "Reiniciar a demonstração",
};

export function SettingsView() {
  const { me, restaurant } = useApp();
  const { data: info } = useSWR<SystemInfo>("v1/system/info");
  const { theme, setTheme } = useTheme();

  return (
    <>
      <PageHeader title="Configurações" description="Sua sessão, suas permissões, o modo dos agentes e a aparência." />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Sessão</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div>
              <span className="text-muted-foreground">Usuário: </span>
              {me?.display_name ?? "—"} {me?.is_demo && <Badge tone="warning">demo</Badge>}
            </div>
            {me?.demo_expires_at && (
              <div>
                <span className="text-muted-foreground">Sua demonstração expira em: </span>
                {dateTime(me.demo_expires_at)}. Depois disso, os dados e a auditoria dela são apagados.
              </div>
            )}
            <div className="pt-2">
              <Button
                variant="outline"
                onClick={() => void logout()}
              >
                <LogOut /> Encerrar sessão
              </Button>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Permissões em {restaurant?.name ?? "—"}</CardTitle>
            <CardDescription>As permissões dependem do seu papel em cada restaurante. Papel atual: {restaurant?.role ?? "—"}.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5 text-sm">
              {Object.entries(PERMISSION_LABEL).map(([key, label]) => {
                const ok = restaurant?.permissions.includes(key);
                return (
                  <li key={key} className="flex items-center justify-between gap-2">
                    <span className={ok ? "" : "text-muted-foreground"}>{label}</span>
                    <Badge tone={ok ? "success" : "neutral"}>{ok ? "permitido" : "não permitido"}</Badge>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Agentes de IA</CardTitle>
            <CardDescription>Configurados no servidor por variáveis de ambiente. Nenhuma chave chega ao navegador.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div className="flex items-center gap-2">
              Modo: <Badge tone={info?.agents.mode === "llm" ? "primary" : "neutral"}>{info?.agents.mode === "llm" ? "LLM" : "Determinístico"}</Badge>
            </div>
            <p className="text-muted-foreground">{info?.agents.label}</p>
            <p className="text-xs text-muted-foreground">{info?.data_notice}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Aparência</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {[
              { key: "light", label: "Claro", icon: Sun },
              { key: "dark", label: "Escuro", icon: Moon },
              { key: "system", label: "Sistema", icon: Monitor },
            ].map(({ key, label, icon: Icon }) => (
              <Button key={key} variant={theme === key ? "default" : "outline"} onClick={() => setTheme(key)} aria-pressed={theme === key}>
                <Icon /> {label}
              </Button>
            ))}
          </CardContent>
        </Card>
      </div>
    </>
  );
}
