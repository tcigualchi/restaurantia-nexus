"use client";

import { useRouter } from "next/navigation";
import * as React from "react";
import { toast } from "sonner";
import useSWR, { useSWRConfig } from "swr";

import { LIVE_POKE_EVENT, apiGet } from "@/lib/api";
import { describeAudit } from "@/lib/format";
import type { LiveAudit, LiveEvent, LiveSnapshot, LiveStatus, Me, Restaurant } from "@/lib/types";

// Live feed transport: short polls to GET /restaurants/{id}/live. Polling (instead of a held-open
// stream) suits serverless hosting, where the same call also advances the simulation. Fast while
// something is happening, slower when idle, paused while the tab is hidden.
const LIVE_BUSY_MS = 1000;
const LIVE_IDLE_MS = 4000;
const LIVE_MAX_BACKOFF_MS = 15000;

interface AppState {
  me: Me | undefined;
  restaurant: Restaurant | undefined;
  restaurants: Restaurant[];
  setRestaurantId: (id: string) => void;
  can: (permission: string) => boolean;
  live: { status: LiveStatus | null; events: LiveEvent[]; audits: LiveAudit[]; connected: boolean };
  rpath: (suffix: string) => string | null;
}

interface LiveState {
  rid: string | null;
  status: LiveStatus | null;
  events: LiveEvent[];
  audits: LiveAudit[];
  connected: boolean;
}

const EMPTY_LIVE: LiveState = { rid: null, status: null, events: [], audits: [], connected: false };

const Ctx = React.createContext<AppState | null>(null);
const STORAGE_KEY = "nexus.restaurant";

function readStored(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(id: string) {
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* storage may be unavailable (private mode); selection still works in memory */
  }
}

const TOAST_ACTIONS = new Set([
  "incident.opened",
  "approval.requested",
  "action.executed",
  "action.failed",
  "agent_run.completed",
  "agent_run.failed",
  "simulation.completed",
]);

export function AppProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const { data: me } = useSWR<Me>("v1/auth/me");
  const restaurants = React.useMemo(() => me?.restaurants ?? [], [me]);
  const [selected, setSelected] = React.useState<string | null>(() => readStored());
  const restaurant =
    restaurants.find((r) => r.id === selected) ??
    restaurants.find((r) => r.template_key === "aurora_pinheiros") ??
    restaurants[0];
  const rid = restaurant?.id;

  const setRestaurantId = React.useCallback((id: string) => {
    writeStored(id);
    setSelected(id);
  }, []);

  // Live state is keyed by restaurant so switching tenants never shows another tenant's feed.
  const [liveState, setLiveState] = React.useState<LiveState>(EMPTY_LIVE);
  const update = React.useCallback(
    (forRid: string, fn: (prev: LiveState) => Partial<LiveState>) =>
      setLiveState((prev) => {
        const base = prev.rid === forRid ? prev : { ...EMPTY_LIVE, rid: forRid };
        return { ...base, ...fn(base) };
      }),
    [],
  );

  React.useEffect(() => {
    if (!rid) return;
    const connectedAt = Date.now();
    const controller = new AbortController();
    let cursor: string | null = null;
    let lastStatus = "";
    let stopped = false;
    let inFlight = false;
    let pokedDuringPoll = false;
    let failures = 0;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    let revalidateTimer: ReturnType<typeof setTimeout> | null = null;

    const revalidate = () => {
      if (revalidateTimer) return;
      revalidateTimer = setTimeout(() => {
        revalidateTimer = null;
        void mutate((key) => typeof key === "string" && key.includes(`restaurants/${rid}`));
      }, 700);
    };

    const notify = (audit: LiveAudit) => {
      if (!TOAST_ACTIONS.has(audit.action) || new Date(audit.created_at).getTime() <= connectedAt - 2000) return;
      const text = `${describeAudit(audit.action)}${audit.title ? `: ${audit.title}` : ""}`;
      if (audit.action === "approval.requested") {
        toast.warning(text, { action: { label: "Revisar", onClick: () => router.push("/approvals") } });
      } else if (audit.action.endsWith("failed")) {
        toast.error(text);
      } else if (audit.action === "incident.opened") {
        toast.warning(text);
      } else {
        toast.success(text);
      }
    };

    const schedule = (ms: number) => {
      if (stopped) return;
      if (pollTimer) clearTimeout(pollTimer);
      pollTimer = setTimeout(() => void poll(), ms);
    };

    const poll = async () => {
      pollTimer = null;
      if (stopped || inFlight || document.visibilityState === "hidden") return; // resumed on visibilitychange
      inFlight = true;
      try {
        const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
        const snapshot = await apiGet<LiveSnapshot>(`v1/restaurants/${rid}/live${query}`, controller.signal);
        if (stopped) return;
        failures = 0;
        cursor = snapshot.cursor;
        update(rid, () => ({ connected: true }));
        const statusKey = JSON.stringify(snapshot.status);
        if (statusKey !== lastStatus) {
          lastStatus = statusKey;
          update(rid, () => ({ status: snapshot.status }));
          revalidate();
        }
        if (snapshot.events.length) {
          const newest: LiveEvent[] = [...snapshot.events].reverse();
          update(rid, (prev) => ({ events: [...newest, ...prev.events].slice(0, 80) }));
          revalidate();
        }
        if (snapshot.audits.length) {
          const newest = [...snapshot.audits].reverse();
          update(rid, (prev) => ({ audits: [...newest, ...prev.audits].slice(0, 50) }));
          revalidate();
          snapshot.audits.forEach(notify);
        }
        const busy = snapshot.status.simulation?.status === "running" || snapshot.status.agents_running > 0;
        schedule(pokedDuringPoll ? 150 : busy ? LIVE_BUSY_MS : LIVE_IDLE_MS);
        pokedDuringPoll = false;
      } catch {
        if (stopped) return;
        failures += 1;
        update(rid, () => ({ connected: false }));
        schedule(Math.min(LIVE_MAX_BACKOFF_MS, LIVE_BUSY_MS * 2 ** failures));
      } finally {
        inFlight = false;
      }
    };

    const resume = () => {
      if (document.visibilityState === "visible" && !inFlight) schedule(0);
    };
    const poke = () => {
      if (inFlight) pokedDuringPoll = true;
      else schedule(150);
    };
    document.addEventListener("visibilitychange", resume);
    window.addEventListener(LIVE_POKE_EVENT, poke);
    void poll();
    return () => {
      stopped = true;
      controller.abort();
      if (pollTimer) clearTimeout(pollTimer);
      if (revalidateTimer) clearTimeout(revalidateTimer);
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener(LIVE_POKE_EVENT, poke);
    };
  }, [rid, mutate, router, update]);

  const live = liveState.rid === rid ? liveState : EMPTY_LIVE;

  const value: AppState = {
    me,
    restaurant,
    restaurants,
    setRestaurantId,
    can: (permission) => !!restaurant?.permissions.includes(permission),
    live: { status: live.status, events: live.events, audits: live.audits, connected: live.connected },
    rpath: (suffix) => (rid ? `v1/restaurants/${rid}${suffix}` : null),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}
