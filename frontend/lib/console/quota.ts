export type Quota = { used: number; cap: number; enabled: boolean };

const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;

/** The database's `my_quota()` answer, checked; anything unexpected is null (the note is then simply not shown). */
export function parseQuota(raw: unknown): Quota | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const { used, cap, enabled } = raw as Record<string, unknown>;
  if (!isCount(used) || !isCount(cap) || typeof enabled !== "boolean") return null;
  return { used, cap, enabled };
}

export function quotaLine(q: Quota): string {
  if (!q.enabled) return "The free allowance is switched off right now.";
  const used = Math.min(q.used, q.cap);
  if (used >= q.cap) return `${q.cap} of ${q.cap} judged responses used. The free allowance is used up.`;
  return `${used} of ${q.cap} judged responses used`;
}
