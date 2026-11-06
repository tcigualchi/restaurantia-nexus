import { AlertTriangle, CheckCircle2, CircleDashed, Clock, Loader2, PauseCircle, XCircle } from "lucide-react";
import type * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "primary" | "success" | "warning" | "danger" | "info";

const RISK: Record<string, { tone: Tone; label: string }> = {
  ok: { tone: "success", label: "OK" },
  watch: { tone: "info", label: "Observar" },
  high: { tone: "warning", label: "Alto" },
  critical: { tone: "danger", label: "Crítico" },
  out: { tone: "danger", label: "Esgotado" },
};

export function RiskBadge({ risk }: { risk: string }) {
  const r = RISK[risk] ?? { tone: "neutral" as Tone, label: risk };
  return <Badge tone={r.tone}>{r.label}</Badge>;
}

const APPROVAL: Record<string, { tone: Tone; label: string }> = {
  pending: { tone: "warning", label: "Pendente" },
  approved: { tone: "info", label: "Aprovada" },
  executed: { tone: "success", label: "Executada" },
  rejected: { tone: "neutral", label: "Rejeitada" },
  expired: { tone: "neutral", label: "Expirada" },
  failed: { tone: "danger", label: "Falhou na revalidação" },
  cancelled: { tone: "neutral", label: "Cancelada" },
};

export function ApprovalBadge({ status }: { status: string }) {
  const s = APPROVAL[status] ?? { tone: "neutral" as Tone, label: status };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}

const RUN: Record<string, { tone: Tone; label: string; icon: React.ReactNode }> = {
  queued: { tone: "neutral", label: "Na fila", icon: <Clock /> },
  running: { tone: "info", label: "Analisando", icon: <Loader2 className="animate-spin" /> },
  awaiting_approval: { tone: "warning", label: "Aguardando aprovação", icon: <PauseCircle /> },
  completed: { tone: "success", label: "Concluída", icon: <CheckCircle2 /> },
  failed: { tone: "danger", label: "Falhou", icon: <XCircle /> },
};

export function RunBadge({ status }: { status: string }) {
  const s = RUN[status] ?? { tone: "neutral" as Tone, label: status, icon: <CircleDashed /> };
  return (
    <Badge tone={s.tone}>
      {s.icon}
      {s.label}
    </Badge>
  );
}

export function ModeBadge({ mode, model }: { mode: string | null; model?: string | null }) {
  if (mode === "llm") return <Badge tone="primary">LLM{model ? ` · ${model}` : ""}</Badge>;
  if (mode === "llm_fallback" || mode === "mixed")
    return <Badge tone="warning">Fallback determinístico</Badge>;
  return <Badge tone="neutral">Determinístico (sem LLM)</Badge>;
}

const SIM: Record<string, { tone: Tone; label: string }> = {
  running: { tone: "success", label: "Em execução" },
  paused: { tone: "warning", label: "Pausada" },
  completed: { tone: "info", label: "Concluída" },
  cancelled: { tone: "neutral", label: "Encerrada" },
};

export const PAUSE_REASON: Record<string, string> = {
  manual: "pausa manual",
  agents_running: "agentes analisando",
  awaiting_approval: "aguardando decisão humana",
};

export function SimBadge({ status, reason }: { status: string; reason?: string | null }) {
  const s = SIM[status] ?? { tone: "neutral" as Tone, label: status };
  return (
    <Badge tone={s.tone}>
      {s.label}
      {status === "paused" && reason ? ` · ${PAUSE_REASON[reason] ?? reason}` : ""}
    </Badge>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function KpiCard({
  label,
  value,
  hint,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  icon?: React.ReactNode;
  tone?: "neutral" | "warning" | "danger" | "success";
}) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        {icon && (
          <div
            className={cn(
              "rounded-md p-1.5 [&_svg]:size-4",
              tone === "danger" && "bg-danger-soft text-danger",
              tone === "warning" && "bg-warning-soft text-accent-foreground",
              tone === "success" && "bg-success-soft text-success",
              tone === "neutral" && "bg-muted text-muted-foreground",
            )}
          >
            {icon}
          </div>
        )}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
    </Card>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-6 py-12 text-center">
      {icon && <div className="text-muted-foreground [&_svg]:size-8">{icon}</div>}
      <div className="text-sm font-medium">{title}</div>
      {description && <div className="max-w-md text-sm text-muted-foreground">{description}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const message = error instanceof Error ? error.message : "Não foi possível carregar os dados.";
  return (
    <div role="alert" className="flex items-center gap-3 rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger">
      <AlertTriangle className="size-4 shrink-0" />
      <span className="flex-1">{message}</span>
      {retry && (
        <button type="button" onClick={retry} className="font-medium underline underline-offset-2 cursor-pointer">
          Tentar novamente
        </button>
      )}
    </div>
  );
}

export function SyntheticNotice({ className }: { className?: string }) {
  return (
    <p className={cn("text-[11px] text-muted-foreground", className)}>
      Dados sintéticos gerados por simulação. Projeto de portfólio sem vínculo com iFood ou outras plataformas.
    </p>
  );
}
