"use client";

import { ArrowRight, KeyRound, Loader2, UserCog, Users } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const PERSONAS = [
  { key: "manager", title: "Gerente", text: "Opera a simulação e pode aprovar ou rejeitar ações.", icon: UserCog },
  { key: "operator", title: "Operador", text: "Opera e observa; não pode aprovar (demonstra o RBAC).", icon: Users },
] as const;

function DemoEntryInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [persona, setPersona] = useState<"manager" | "operator">("manager");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(params.get("expired") ? "Sua sessão expirou. Entre novamente." : null);
  const [showLogin, setShowLogin] = useState(false);

  async function post(url: string, body: unknown) {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error?.message ?? "Não foi possível entrar.");
      router.push("/overview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Não foi possível entrar.");
      setBusy(false);
    }
  }

  return (
    <Card className="shadow-lg">
      <CardHeader>
        <CardTitle className="text-base">Experimente em 2 minutos</CardTitle>
        <CardDescription>
          Cada visitante recebe um sandbox isolado com dois restaurantes sintéticos. Expira automaticamente.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <fieldset className="grid gap-2" aria-label="Escolha uma persona">
          {PERSONAS.map(({ key, title, text, icon: Icon }) => (
            <label
              key={key}
              className={cn(
                "flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors hover:bg-muted/60",
                persona === key && "border-primary ring-1 ring-primary",
              )}
            >
              <input
                type="radio"
                name="persona"
                value={key}
                checked={persona === key}
                onChange={() => setPersona(key)}
                className="mt-1 accent-[var(--primary)]"
              />
              <Icon className="mt-0.5 size-4 text-primary" />
              <span>
                <span className="block text-sm font-medium">{title}</span>
                <span className="block text-xs text-muted-foreground">{text}</span>
              </span>
            </label>
          ))}
        </fieldset>
        <Button size="lg" className="w-full" disabled={busy} onClick={() => post("/api/session/demo", { persona })}>
          {busy ? <Loader2 className="animate-spin" /> : <ArrowRight />}
          Entrar no modo demo
        </Button>
        {error && (
          <p role="alert" className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        <div className="border-t pt-3">
          <button
            type="button"
            onClick={() => setShowLogin((v) => !v)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
            aria-expanded={showLogin}
          >
            <KeyRound className="size-3.5" /> Acesso com usuário local (seed)
          </button>
          {showLogin && (
            <form
              className="mt-3 grid gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                const form = new FormData(e.currentTarget);
                void post("/api/session/login", { email: form.get("email"), password: form.get("password") });
              }}
            >
              <Label htmlFor="email">E-mail</Label>
              <Input id="email" name="email" type="email" autoComplete="username" required />
              <Label htmlFor="password">Senha</Label>
              <Input id="password" name="password" type="password" autoComplete="current-password" minLength={8} required />
              <Button type="submit" variant="outline" disabled={busy}>
                Entrar
              </Button>
            </form>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function DemoEntry() {
  return (
    <Suspense>
      <DemoEntryInner />
    </Suspense>
  );
}
