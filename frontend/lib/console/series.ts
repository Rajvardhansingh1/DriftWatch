import type { SignalName, SignalPoint, SignalSeries } from "@/lib/types";

export const SIGNAL_NAMES: SignalName[] = [
  "embedding_drift",
  "self_consistency",
  "canary_accuracy",
  "judge_trend",
  "hallucination_score",
  "combined_score",
];

export const MAX_POINTS = 500;

export type Row = { signal: string; value: number; occurred_at: string };

const isSignal = (s: string): s is SignalName => (SIGNAL_NAMES as string[]).includes(s);
const byTime = (a: SignalPoint, b: SignalPoint) => Date.parse(a.timestamp) - Date.parse(b.timestamp);

export function emptySeries(): SignalSeries {
  return Object.fromEntries(SIGNAL_NAMES.map((n) => [n, [] as SignalPoint[]])) as SignalSeries;
}

export function rowsToSeries(rows: Row[], max = MAX_POINTS): SignalSeries {
  const series = emptySeries();
  for (const r of rows) {
    if (isSignal(r.signal) && Number.isFinite(r.value)) {
      series[r.signal].push({ timestamp: r.occurred_at, value: r.value });
    }
  }
  for (const name of SIGNAL_NAMES) {
    series[name].sort(byTime);
    if (series[name].length > max) series[name] = series[name].slice(-max);
  }
  return series;
}

export function appendPoint(series: SignalSeries, row: Row, max = MAX_POINTS): SignalSeries {
  if (!isSignal(row.signal) || !Number.isFinite(row.value)) return series;
  const current = series[row.signal];
  if (current.some((p) => p.timestamp === row.occurred_at && p.value === row.value)) return series;
  const next = [...current, { timestamp: row.occurred_at, value: row.value }].sort(byTime);
  return { ...series, [row.signal]: next.length > max ? next.slice(-max) : next };
}

export function hourlyToSeries(rows: { signal: string; hour: string; avg_value: number }[]): SignalSeries {
  return rowsToSeries(rows.map((r) => ({ signal: r.signal, value: r.avg_value, occurred_at: r.hour })));
}
