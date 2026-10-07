import test from "node:test";
import assert from "node:assert/strict";
import { SIGNAL_PANELS, COMBINED_PANEL } from "../lib/panels";
import {
  isLiveRange, isUuid, parseKeyName, parseProjectName, parseRange, rangeToSince,
} from "../lib/console/validate";
import { appendPoint, emptySeries, hourlyToSeries, rowsToSeries, SIGNAL_NAMES } from "../lib/console/series";
import { loadSeries } from "../lib/console/data";
import { subscribeToProject, type ClientLike } from "../lib/console/realtime";

test("panels: five detector panels plus combined, canary and judge are higher-is-better", () => {
  assert.equal(SIGNAL_PANELS.length, 5);
  assert.equal(COMBINED_PANEL.key, "combined_score");
  const better = SIGNAL_PANELS.filter((p) => p.higherIsBetter).map((p) => p.key).sort();
  assert.deepEqual(better, ["canary_accuracy", "judge_trend"]);
});

test("isUuid accepts uuids only", () => {
  assert.ok(isUuid("11111111-1111-4111-8111-111111111111"));
  for (const bad of ["", "nope", "11111111-1111-4111-8111-11111111111", null, 5, "../etc/passwd"]) {
    assert.equal(isUuid(bad as unknown), false, String(bad));
  }
});

test("names are trimmed, collapsed, bounded and control-char free", () => {
  assert.deepEqual(parseProjectName("  My   app "), { ok: true, value: "My app" });
  assert.equal(parseProjectName("").ok, false);
  assert.equal(parseProjectName("x".repeat(65)).ok, false);
  assert.equal(parseProjectName("a\u0000b").ok, false);
  assert.equal(parseKeyName(12 as unknown).ok, false);
  assert.deepEqual(parseKeyName("laptop"), { ok: true, value: "laptop" });
});

test("ranges parse with a safe default and map to a start time", () => {
  assert.equal(parseRange("7d"), "7d");
  assert.equal(parseRange("evil"), "24h");
  assert.equal(parseRange(undefined), "24h");
  const now = new Date("2026-10-07T12:00:00Z");
  assert.equal(rangeToSince("1h", now).toISOString(), "2026-10-07T11:00:00.000Z");
  assert.equal(isLiveRange("24h"), true);
  assert.equal(isLiveRange("30d"), false);
});

test("rowsToSeries groups, sorts ascending, ignores unknown signals and bad values", () => {
  const s = rowsToSeries([
    { signal: "combined_score", value: 0.3, occurred_at: "2026-10-07T10:02:00Z" },
    { signal: "combined_score", value: 0.1, occurred_at: "2026-10-07T10:00:00Z" },
    { signal: "bogus", value: 1, occurred_at: "2026-10-07T10:00:00Z" },
    { signal: "judge_trend", value: Number.NaN, occurred_at: "2026-10-07T10:00:00Z" },
  ]);
  assert.deepEqual(s.combined_score.map((p) => p.value), [0.1, 0.3]);
  assert.equal(s.judge_trend.length, 0);
});

test("rowsToSeries keeps only the latest `max` points", () => {
  const rows = Array.from({ length: 10 }, (_, i) => ({
    signal: "embedding_drift", value: i / 10, occurred_at: `2026-10-07T10:0${i}:00Z`,
  }));
  assert.deepEqual(rowsToSeries(rows, 3).embedding_drift.map((p) => p.value), [0.7, 0.8, 0.9]);
});

test("appendPoint is immutable, ordered, deduplicated and bounded", () => {
  const base = emptySeries();
  const row = { signal: "combined_score", value: 0.5, occurred_at: "2026-10-07T10:00:00Z" };
  const a = appendPoint(base, row);
  assert.equal(base.combined_score.length, 0);
  assert.equal(a.combined_score.length, 1);
  assert.equal(appendPoint(a, row).combined_score.length, 1); // redelivery after reconnect
  const b = appendPoint(a, { ...row, value: 0.2, occurred_at: "2026-10-07T09:00:00Z" });
  assert.deepEqual(b.combined_score.map((p) => p.value), [0.2, 0.5]);
  let s = base;
  for (let i = 0; i < 5; i++) s = appendPoint(s, { ...row, value: i, occurred_at: `2026-10-07T11:0${i}:00Z` }, 3);
  assert.equal(s.combined_score.length, 3);
  assert.equal(appendPoint(base, { ...row, signal: "bogus" }), base);
});

test("hourlyToSeries maps avg_value", () => {
  const s = hourlyToSeries([{ signal: "combined_score", hour: "2026-10-07T10:00:00Z", avg_value: 0.4 }]);
  assert.deepEqual(s.combined_score, [{ timestamp: "2026-10-07T10:00:00Z", value: 0.4 }]);
});

test("subscribeToProject listens to INSERT on one project only and reports status", () => {
  const calls: { on?: [string, Record<string, unknown>]; removed?: boolean } = {};
  const names: string[] = [];
  let statusCb: ((s: string) => void) | undefined;
  let rowCb: ((p: { new: unknown }) => void) | undefined;
  const channel = {
    on(type: string, filter: Record<string, unknown>, cb: (p: { new: unknown }) => void) {
      calls.on = [type, filter]; rowCb = cb; return channel;
    },
    subscribe(cb?: (s: string) => void) { statusCb = cb; return channel; },
  };
  const client: ClientLike = {
    channel: (name: string) => { names.push(name); return channel; },
    removeChannel: () => { calls.removed = true; },
  };
  const rows: unknown[] = [];
  const statuses: string[] = [];
  const stop = subscribeToProject(client, "11111111-1111-4111-8111-111111111111", (r) => rows.push(r), (s) => statuses.push(s));
  assert.equal(calls.on![0], "postgres_changes");
  assert.deepEqual(calls.on![1], {
    event: "INSERT", schema: "public", table: "signal_records",
    filter: "project_id=eq.11111111-1111-4111-8111-111111111111",
  });
  statusCb!("SUBSCRIBED"); statusCb!("CHANNEL_ERROR"); statusCb!("JOINING");
  assert.deepEqual(statuses, ["live", "offline", "connecting"]);
  rowCb!({ new: { signal: "combined_score", value: 0.2, occurred_at: "2026-10-07T10:00:00Z" } });
  rowCb!({ new: { signal: 5 } }); // malformed payload is dropped
  assert.equal(rows.length, 1);
  stop();
  assert.equal(calls.removed, true);
  assert.match(names[0], /^project-11111111-1111-4111-8111-111111111111-[0-9a-f-]{36}$/);
  subscribeToProject(client, "11111111-1111-4111-8111-111111111111", () => {}, () => {});
  assert.notEqual(names[0], names[1]);
});

test("subscribeToProject refuses a non-uuid project id", () => {
  const client = { channel() { throw new Error("must not subscribe"); }, removeChannel() {} } as unknown as ClientLike;
  assert.throws(() => subscribeToProject(client, "x; drop", () => {}, () => {}));
});

function fakeClient(log: { table: string; calls: [string, unknown[]][] }[]) {
  return {
    from(table: string) {
      const entry = { table, calls: [] as [string, unknown[]][] };
      log.push(entry);
      const q: Record<string, unknown> = {};
      for (const m of ["select", "eq", "gte", "order", "limit"]) {
        q[m] = (...args: unknown[]) => { entry.calls.push([m, args]); return q; };
      }
      q.then = (res: (v: unknown) => unknown) => res({ data: [], error: null });
      return q;
    },
  } as never;
}

test("loadSeries raw ranges issue one limited query per signal; 30d reads hourly", async () => {
  const log: { table: string; calls: [string, unknown[]][] }[] = [];
  await loadSeries(fakeClient(log), "p1", "24h");
  assert.equal(log.length, 6);
  const names = log.map((l) => l.calls.find(([m, a]) => m === "eq" && a[0] === "signal")![1][1]);
  assert.deepEqual(names, SIGNAL_NAMES);
  for (const l of log) {
    assert.equal(l.table, "signal_records");
    assert.deepEqual(l.calls.find(([m]) => m === "limit")![1], [500]);
  }
  const hourly: typeof log = [];
  await loadSeries(fakeClient(hourly), "p1", "30d");
  assert.deepEqual(hourly.map((l) => l.table), ["signal_hourly"]);
});
