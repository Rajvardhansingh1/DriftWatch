import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { test } from "node:test";
import {
  connectModelCore, deleteConnectionCore, estimateUsage, parseConnectInput, parseProbes, runStatus, setProbesCore,
  STARTER_PROBES, updateConnectionCore, validateProviderKey, type ConnectDeps,
} from "../lib/connect/core";

const KEY = "gsk_" + "k".repeat(40);
const PROJECT = randomUUID();
const input = { provider: "groq", model: "some-model", apiKey: KEY, intervalMinutes: 60, monthlyBudget: 2000 };

type Call = { fn: string; args: Record<string, unknown> };
function client(error: { code?: string; message?: string } | null = null) {
  const calls: Call[] = [];
  return {
    calls,
    rpc: async (fn: string, args: Record<string, unknown> = {}) => {
      calls.push({ fn, args });
      return { data: null, error };
    },
  };
}
function deps(over: Partial<ConnectDeps> = {}): ConnectDeps & { sealed: unknown[] } {
  const sealed: unknown[] = [];
  return {
    sealed,
    enabled: true,
    publicKey: "UFVCTElDLUtFWQ==",
    keyId: 2,
    newId: () => "11111111-2222-4333-8444-555555555555",
    check: async () => "ok",
    seal: (plain, modelId, keyId, pub) => {
      sealed.push({ plain, modelId, keyId, pub });
      return { key_id: keyId, ephemeral: "RVBI", nonce: "Tk9OQ0U=", ciphertext: "Q0lQSEVS" };
    },
    ...over,
  };
}

test("input is parsed strictly, with the documented defaults", () => {
  assert.deepEqual(parseConnectInput({ provider: "openai", model: "gpt-x", apiKey: KEY }), {
    ok: true, value: { provider: "openai", model: "gpt-x", apiKey: KEY, intervalMinutes: 60, monthlyBudget: 2000 },
  });
  for (const bad of [
    { ...input, provider: "anthropic" }, { ...input, provider: "" }, { ...input, model: "has space" }, { ...input, model: "" },
    { ...input, apiKey: "short" }, { ...input, apiKey: "has space in it here" }, { ...input, apiKey: "k".repeat(600) },
    { ...input, intervalMinutes: 5 }, { ...input, intervalMinutes: 2000 }, { ...input, intervalMinutes: 1.5 },
    { ...input, monthlyBudget: 0 }, { ...input, monthlyBudget: 1_000_000 }, null, "x", [],
  ]) {
    const r = parseConnectInput(bad);
    assert.equal(r.ok, false, JSON.stringify(bad));
    assert.ok(!JSON.stringify(r).includes(KEY), "an error must not echo the key");
  }
});

test("connecting seals the key before it leaves, and sends no plaintext to the database", async () => {
  const c = client();
  const d = deps();
  const r = await connectModelCore(c, d, PROJECT, input);
  assert.deepEqual(r, { ok: true, last4: KEY.slice(-4) });
  assert.equal(c.calls.length, 1);
  assert.equal(c.calls[0].fn, "connect_model");
  const sent = JSON.stringify(c.calls[0].args);
  assert.ok(!sent.includes(KEY) && !sent.includes("apiKey"), "the database never sees the plaintext key");
  assert.deepEqual(c.calls[0].args, {
    p_project_id: PROJECT, p_model_id: "11111111-2222-4333-8444-555555555555", p_provider: "groq", p_model: "some-model",
    p_last4: KEY.slice(-4), p_key_id: 2, p_ephemeral: "RVBI", p_nonce: "Tk9OQ0U=", p_ciphertext: "Q0lQSEVS",
    p_interval_minutes: 60, p_monthly_budget: 2000,
  });
  assert.deepEqual(d.sealed, [{ plain: KEY, modelId: "11111111-2222-4333-8444-555555555555", keyId: 2, pub: "UFVCTElDLUtFWQ==" }]);
  assert.ok(!JSON.stringify(r).includes(KEY.slice(0, -4)), "only the last four characters come back");
});

test("the provider is asked first: a rejected or unreachable key is never stored", async () => {
  for (const [verdict, expect] of [["rejected", /rejected/i], ["unreachable", /could not reach/i]] as const) {
    const c = client();
    const d = deps({ check: async () => verdict });
    const r = await connectModelCore(c, d, PROJECT, input);
    assert.equal(r.ok, false);
    assert.match((r as { error: string }).error, expect);
    assert.equal(c.calls.length, 0);
    assert.equal(d.sealed.length, 0);
    assert.ok(!JSON.stringify(r).includes(KEY));
  }
});

test("when the feature is off, or the public key is missing, nothing happens", async () => {
  for (const d of [deps({ enabled: false }), deps({ publicKey: "" })]) {
    const c = client();
    const r = await connectModelCore(c, d, PROJECT, input);
    assert.equal(r.ok, false);
    assert.equal(c.calls.length, 0);
  }
  const c = client();
  assert.equal((await connectModelCore(c, deps(), "not-a-uuid", input)).ok, false);
  assert.equal(c.calls.length, 0);
});

test("database errors become fixed sentences and never contain the key", async () => {
  for (const code of ["PT401", "PT403", "PT503", "PT422", "XX000"]) {
    const c = client({ code, message: `secret ${KEY}` });
    const r = await connectModelCore(c, deps(), PROJECT, input);
    assert.equal(r.ok, false);
    assert.ok(!JSON.stringify(r).includes(KEY) && !JSON.stringify(r).includes("secret "), code);
  }
});

test("a thrown error while sealing or calling is also reduced and key-free", async () => {
  const boom = deps({ seal: () => { throw new Error("failed for " + KEY); } });
  const r = await connectModelCore(client(), boom, PROJECT, input);
  assert.equal(r.ok, false);
  assert.ok(!JSON.stringify(r).includes(KEY));
});

test("provider validation uses only the fixed host and reports a verdict", async () => {
  const seen: string[] = [];
  const f = (status: number) => (async (url: string, init: RequestInit) => {
    seen.push(url);
    assert.equal((init.headers as Record<string, string>).Authorization, `Bearer ${KEY}`);
    assert.equal(init.redirect, "error");
    return new Response("{}", { status });
  }) as unknown as typeof fetch;
  assert.equal(await validateProviderKey(f(200), "groq", "m", KEY), "ok");
  assert.equal(await validateProviderKey(f(401), "openai", "m", KEY), "rejected");
  assert.equal(await validateProviderKey(f(403), "openai", "m", KEY), "rejected");
  assert.equal(await validateProviderKey(f(500), "groq", "m", KEY), "unreachable");
  assert.equal(await validateProviderKey((async () => { throw new TypeError("net"); }) as unknown as typeof fetch, "groq", "m", KEY), "unreachable");
  assert.deepEqual(seen.slice(0, 3), [
    "https://api.groq.com/openai/v1/chat/completions", "https://api.openai.com/v1/chat/completions", "https://api.openai.com/v1/chat/completions",
  ]);
  assert.equal(await validateProviderKey(f(200), "evil", "m", KEY), "unreachable");
  assert.equal(seen.length, 4 + 0, "an unknown provider makes no request");
});

test("probes: one to five, trimmed, with a known match type", () => {
  assert.equal(parseProbes(STARTER_PROBES).ok, true);
  assert.equal(STARTER_PROBES.length, 5);
  assert.equal(parseProbes([]).ok, false);
  assert.equal(parseProbes(Array.from({ length: 6 }, () => ({ prompt: "p", expected: "e", match_type: "contains" }))).ok, false);
  for (const bad of [
    [{ prompt: "", expected: "e", match_type: "contains" }], [{ prompt: "p", expected: "", match_type: "contains" }],
    [{ prompt: "p", expected: "e", match_type: "regex" }], [{ prompt: "x".repeat(501), expected: "e", match_type: "contains" }],
    [{ prompt: "p", expected: "x".repeat(201), match_type: "exact" }], ["str"], [null], "nope",
  ]) assert.equal(parseProbes(bad).ok, false, JSON.stringify(bad).slice(0, 60));
  const r = parseProbes([{ prompt: "  Say OK  ", expected: " OK ", match_type: "contains" }]);
  assert.deepEqual(r.ok && r.value, [{ prompt: "Say OK", expected: "OK", match_type: "contains" }]);
});

test("the starter probes are neutral: no personal data, short, and answerable", () => {
  for (const p of STARTER_PROBES) {
    assert.ok(p.prompt.length < 200 && p.expected.length < 40);
    assert.ok(!/@|\d{6,}|password|secret/i.test(p.prompt));
  }
});

test("setting probes, updating settings and deleting go through the right functions", async () => {
  let c = client();
  assert.deepEqual(await setProbesCore(c, PROJECT, STARTER_PROBES), { ok: true });
  assert.deepEqual(c.calls[0], { fn: "set_probes", args: { p_project_id: PROJECT, p_probes: STARTER_PROBES } });
  c = client();
  assert.deepEqual(await updateConnectionCore(c, PROJECT, { intervalMinutes: 30, monthlyBudget: 500, enabled: false }), { ok: true });
  assert.deepEqual(c.calls[0], { fn: "update_connected_model", args: { p_project_id: PROJECT, p_interval_minutes: 30, p_monthly_budget: 500, p_enabled: false } });
  assert.equal((await updateConnectionCore(client(), PROJECT, { intervalMinutes: 5, monthlyBudget: 500, enabled: true })).ok, false);
  c = client();
  assert.deepEqual(await deleteConnectionCore(c, PROJECT), { ok: true });
  assert.equal(c.calls[0].fn, "delete_connected_model");
  for (const f of [() => setProbesCore(client(), "x", STARTER_PROBES), () => deleteConnectionCore(client(), "x")]) assert.equal((await f()).ok, false);
});

test("usage estimate is honest: calls and a token ceiling, never a price", () => {
  const e = estimateUsage({ probes: 5, intervalMinutes: 60, monthlyBudget: 2000 });
  assert.equal(e.callsPerRun, 7);
  assert.equal(e.runsPerMonth, Math.floor((30 * 24 * 60) / 60));
  assert.equal(e.callsPerMonth, 2000, "the budget is the ceiling");
  assert.ok(e.tokensCeiling > 0 && e.tokensCeiling <= 2000 * 450);
  assert.equal(estimateUsage({ probes: 1, intervalMinutes: 1440, monthlyBudget: 100000 }).callsPerMonth, 3 * 30);
});

test("run status: never run, healthy, late and failing are told apart", () => {
  const now = Date.parse("2026-10-13T12:00:00Z");
  const base = { enabled: true, interval_minutes: 60, last_run_at: null, last_error: null };
  assert.equal(runStatus(base, now), "waiting");
  assert.equal(runStatus({ ...base, last_run_at: "2026-10-13T11:30:00Z" }, now), "ok");
  assert.equal(runStatus({ ...base, last_run_at: "2026-10-13T09:00:00Z" }, now), "late");
  assert.equal(runStatus({ ...base, last_run_at: "2026-10-13T11:30:00Z", last_error: "x" }, now), "error");
  assert.equal(runStatus({ ...base, enabled: false }, now), "paused");
});
