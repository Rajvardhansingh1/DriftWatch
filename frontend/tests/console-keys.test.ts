import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { eventExample } from "../components/console/KeyManager";

test("keys page is server-rendered from RLS data and never receives a key", () => {
  const src = readFileSync("app/dashboard/[projectId]/keys/page.tsx", "utf8");
  assert.match(src, /listKeys\(/);
  assert.match(src, /isUuid\(/);
  assert.match(src, /notFound\(\)/);
  assert.doesNotMatch(src, /createApiKey/); // creation happens only in the client component
});

test("keys page validates the user server-side in the required order", () => {
  const src = readFileSync("app/dashboard/[projectId]/keys/page.tsx", "utf8");
  const order = ["isUuid(", "createServerSupabase(", "auth.getUser(", "getProject(", "listKeys("].map((s) => src.indexOf(s));
  assert.ok(order.every((i) => i >= 0), "all calls present");
  assert.deepEqual([...order].sort((a, b) => a - b), order);
  assert.doesNotMatch(src, /getSession\(/);
});

test("KeyManager shows a created key from component state only", () => {
  const src = readFileSync("components/console/KeyManager.tsx", "utf8");
  assert.match(src.trimStart(), /^"use client";/);
  assert.match(src, /createApiKey\(/);
  assert.match(src, /revokeApiKey\(/);
  assert.doesNotMatch(src, /localStorage|sessionStorage|document\.cookie|console\./);
  assert.doesNotMatch(src, /router\.(push|replace)\([^)]*key/i); // never in a URL
});

test("KeyManager handles thrown server actions and always resets busy", () => {
  const src = readFileSync("components/console/KeyManager.tsx", "utf8");
  assert.match(src, /catch/);
  assert.match(src, /finally\s*\{\s*setBusy\(false\)/);
  assert.match(src, /Could not create the key/);
  assert.match(src, /Could not revoke the key/);
});

test("event example uses the RPC endpoint and the key placeholder, not a real key", () => {
  const text = eventExample("https://abc.supabase.co", "sb_publishable_x", "YOUR_API_KEY");
  assert.match(text, /\/rest\/v1\/rpc\/ingest_event/);
  assert.match(text, /"p_api_key": "YOUR_API_KEY"/);
  assert.match(text, /apikey: sb_publishable_x/);
  assert.doesNotMatch(text, /dw_[0-9a-f]{10}_/);
});

test("event example uses the sample values when given and keeps placeholders otherwise", () => {
  const sample = { eventId: "11111111-1111-4111-8111-111111111111", occurredAt: "2026-10-08T10:00:00.000Z" };
  const withSample = eventExample("https://abc.supabase.co", "sb_publishable_x", "dw_key", sample);
  assert.doesNotMatch(withSample, /</);
  assert.match(withSample, new RegExp(sample.eventId));
  assert.match(withSample, new RegExp(sample.occurredAt));
  assert.match(eventExample("https://abc.supabase.co", "k", "K"), /<a new uuid>/);
});

test("KeyManager UX guards: one key at a time, revoke label, copy failure, cleared error", () => {
  const src = readFileSync("components/console/KeyManager.tsx", "utf8");
  assert.match(src, /disabled=\{busy \|\| created !== null\}/);
  assert.match(src, /aria-label=\{confirming === k\.id \? `Click again to revoke \$\{k\.name\}` : `Revoke \$\{k\.name\}`\}/);
  assert.match(src, /Copy failed\. Select the key above/);
  assert.match(src, /aria-live="polite"/);
  assert.match(src, /setConfirming\(null\);\s*setError\(""\)/);
});

test("copy status is announced by an always-mounted live region", () => {
  const src = readFileSync("components/console/KeyManager.tsx", "utf8");
  assert.match(src, /<p aria-live="polite"[^>]*>\{copied \? "Copied" : ""\}<\/p>/);
  assert.doesNotMatch(src, /<span aria-live/);
});
