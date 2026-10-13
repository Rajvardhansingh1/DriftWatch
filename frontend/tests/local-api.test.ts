import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiError, getJson, openSession, syncChip, tokenFromHash, toSeries } from "../local/api";

test("the token is read from the URL fragment only", () => {
  assert.equal(tokenFromHash("#token=abc_DEF-123"), "abc_DEF-123");
  assert.equal(tokenFromHash("#x=1&token=abc"), "abc");
  assert.equal(tokenFromHash(""), null);
  assert.equal(tokenFromHash("#token="), null);
  assert.equal(tokenFromHash("#other=abc"), null);
  assert.equal(tokenFromHash("?token=abc"), null);
});

test("openSession posts the token as JSON and reports whether it worked", async () => {
  const calls: { url: string; init: RequestInit }[] = [];
  const ok = async (url: string, init: RequestInit) => { calls.push({ url, init }); return new Response(null, { status: 204 }); };
  assert.equal(await openSession(ok as unknown as typeof fetch, "tok"), true);
  assert.equal(calls[0].url, "/session");
  assert.equal(calls[0].init.method, "POST");
  assert.equal((calls[0].init.headers as Record<string, string>)["Content-Type"], "application/json");
  assert.equal(calls[0].init.body, JSON.stringify({ token: "tok" }));
  assert.equal(calls[0].init.credentials, "same-origin");
  const bad = async () => new Response("{}", { status: 401 });
  assert.equal(await openSession(bad as unknown as typeof fetch, "tok"), false);
  const down = async () => { throw new TypeError("network"); };
  assert.equal(await openSession(down as unknown as typeof fetch, "tok"), false);
});

test("getJson returns the body, and throws an ApiError carrying the status", async () => {
  const f = async () => new Response(JSON.stringify({ a: 1 }), { status: 200 });
  assert.deepEqual(await getJson(f as unknown as typeof fetch, "/api/status"), { a: 1 });
  const denied = async () => new Response("{}", { status: 401 });
  await assert.rejects(() => getJson(denied as unknown as typeof fetch, "/api/status"), (e: unknown) => e instanceof ApiError && e.status === 401);
});

test("toSeries keeps valid points, drops junk and fills missing signals", () => {
  const s = toSeries({
    embedding_drift: [{ timestamp: "2026-10-13T10:00:00+00:00", value: 0.1 }, { timestamp: "x", value: Number.NaN }, { value: 1 }, null, "str"],
    combined_score: "not an array",
    unknown_signal: [{ timestamp: "t", value: 1 }],
  });
  assert.deepEqual(s.embedding_drift, [{ timestamp: "2026-10-13T10:00:00+00:00", value: 0.1 }]);
  assert.deepEqual(s.combined_score, []);
  assert.deepEqual(s.judge_trend, []);
  assert.equal("unknown_signal" in s, false);
  assert.deepEqual(toSeries(null).embedding_drift, []);
});

test("syncChip maps the agent's sync state onto the shared chip", () => {
  assert.deepEqual(syncChip({ sync: { state: "synced", pending: 0 } }), { state: "synced" });
  assert.deepEqual(syncChip({ sync: { state: "pending", pending: 12 } }), { state: "pending", detail: "12" });
  assert.deepEqual(syncChip({ sync: { state: "offline", pending: 3 } }), { state: "offline" });
  assert.deepEqual(syncChip({ sync: { state: "paused", pending: 3 } }), { state: "paused" });
  assert.deepEqual(syncChip(null), { state: "offline" });
  assert.deepEqual(syncChip({ sync: { state: "weird", pending: 1 } }), { state: "offline" });
});
