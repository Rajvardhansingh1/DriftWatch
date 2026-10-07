const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(s: unknown): s is string {
  return typeof s === "string" && UUID_RE.test(s);
}

export type Parsed = { ok: true; value: string } | { ok: false; error: string };

function parseName(raw: unknown, what: string): Parsed {
  if (typeof raw !== "string") return { ok: false, error: `${what} is required` };
  const value = raw.trim().replace(/\s+/g, " ");
  if (value.length < 1 || value.length > 64) {
    return { ok: false, error: `${what} must be 1 to 64 characters` };
  }
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f\u007f]/.test(value)) return { ok: false, error: `${what} has invalid characters` };
  return { ok: true, value };
}

export const parseProjectName = (raw: unknown): Parsed => parseName(raw, "Project name");
export const parseKeyName = (raw: unknown): Parsed => parseName(raw, "Key name");

export const RANGES = ["1h", "24h", "7d", "30d"] as const;
export type Range = (typeof RANGES)[number];

export function parseRange(raw: unknown): Range {
  return (RANGES as readonly string[]).includes(raw as string) ? (raw as Range) : "24h";
}

const HOURS: Record<Range, number> = { "1h": 1, "24h": 24, "7d": 168, "30d": 720 };

export function rangeToSince(range: Range, now: Date = new Date()): Date {
  return new Date(now.getTime() - HOURS[range] * 3_600_000);
}

// 30d reads the hourly rollup, which is not pushed live.
export const isLiveRange = (range: Range): boolean => range !== "30d";
