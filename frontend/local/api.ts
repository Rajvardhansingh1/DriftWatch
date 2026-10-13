import type { SyncState } from "@/components/SyncChip";
import type { SignalSeries } from "@/lib/types";

export const RANGES = ["1h", "24h", "7d", "30d"] as const;
export type LocalRange = (typeof RANGES)[number];

const SIGNALS: (keyof SignalSeries)[] = [
  "embedding_drift",
  "self_consistency",
  "canary_accuracy",
  "judge_trend",
  "hallucination_score",
  "combined_score",
];

export class ApiError extends Error {
  constructor(public status: number) {
    super(`request failed (${status})`);
  }
}

/** The one-time token the CLI puts in the URL fragment. A fragment is never sent to a server. */
export function tokenFromHash(hash: string): string | null {
  const m = /^#(?:.*&)?token=([A-Za-z0-9_-]+)(?:&.*)?$/.exec(hash);
  return m ? m[1] : null;
}

/** Trades the token for the HttpOnly session cookie. Never throws. */
export async function openSession(fetchFn: typeof fetch, token: string): Promise<boolean> {
  try {
    const r = await fetchFn("/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      credentials: "same-origin",
    });
    return r.status === 204;
  } catch {
    return false;
  }
}

export async function getJson<T = unknown>(fetchFn: typeof fetch, path: string): Promise<T> {
  const r = await fetchFn(path, { credentials: "same-origin", cache: "no-store" });
  if (!r.ok) throw new ApiError(r.status);
  return (await r.json()) as T;
}

/** The agent's answer, checked point by point: anything that is not a finite number with a timestamp is dropped. */
export function toSeries(raw: unknown): SignalSeries {
  const out = Object.fromEntries(SIGNALS.map((n) => [n, []])) as unknown as SignalSeries;
  if (!raw || typeof raw !== "object") return out;
  for (const name of SIGNALS) {
    const points = (raw as Record<string, unknown>)[name];
    if (!Array.isArray(points)) continue;
    for (const p of points) {
      if (p && typeof p === "object") {
        const { timestamp, value } = p as { timestamp?: unknown; value?: unknown };
        if (typeof timestamp === "string" && typeof value === "number" && Number.isFinite(value)) {
          out[name].push({ timestamp, value });
        }
      }
    }
  }
  return out;
}

type SyncStatus = { sync?: { state?: string; pending?: number } } | null;

/** The shared sync chip, fed from the agent's outbox state. Anything unexpected reads as offline, never as synced. */
export function syncChip(status: SyncStatus): { state: SyncState; detail?: string } {
  const sync = status?.sync;
  switch (sync?.state) {
    case "synced":
      return { state: "synced" };
    case "pending":
      return { state: "pending", detail: String(sync.pending ?? 0) };
    case "paused":
      return { state: "paused" };
    default:
      return { state: "offline" };
  }
}
