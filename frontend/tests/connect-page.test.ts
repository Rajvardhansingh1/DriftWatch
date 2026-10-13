import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ConnectManager, type ConnectedModel } from "../components/console/ConnectManager";

const PROJECT = "11111111-2222-4333-8444-555555555555";
const model: ConnectedModel = {
  provider: "groq", model: "some-model", last4: "wxyz", interval_minutes: 60, monthly_budget: 2000, enabled: true,
  calls_this_month: 35, last_run_at: "2026-10-13T11:30:00.000Z", last_error: null,
};
const html = (over: Partial<Parameters<typeof ConnectManager>[0]> = {}) =>
  renderToStaticMarkup(React.createElement(ConnectManager, { projectId: PROJECT, model: null, probes: [], status: "waiting", canEdit: true, ...over }));

test("before connecting: the honest warnings are there and the key field is a password field", () => {
  const out = html();
  assert.match(out, /fixed questions<\/strong>, not your app&#x27;s real traffic/);
  assert.match(out, /uses your provider account/);
  assert.match(out, /type="password"[^>]*autoComplete="off"|autoComplete="off"[^>]*type="password"|type="password"/);
  assert.match(out, /Connect a model/);
  assert.doesNotMatch(out, /Delete key and connection/);
});

test("once connected: only the last four of the key are shown, with status, budget use and the schedule controls", () => {
  const out = html({ model, status: "ok", probes: [{ prompt: "Say OK", expected: "OK", match_type: "contains" }] });
  assert.match(out, /wxyz/);
  assert.match(out, /Running normally/);
  assert.match(out, /35 of 2000 calls used this month/);
  assert.match(out, /2026-10-13 11:30 UTC/);
  assert.match(out, /Usage estimate/);
  assert.match(out, /does not know it|DriftWatch does not know/);
  assert.match(out, /Delete key and connection/);
  assert.doesNotMatch(out, /gsk_|sk-[A-Za-z0-9]{10}/);
});

test("a late runner and a failing run are shown plainly", () => {
  assert.match(html({ model, status: "late" }), /last run is late/i);
  const failing = html({ model: { ...model, last_error: "The provider rejected the key. Connect again with a new key." }, status: "error" });
  assert.match(failing, /The last run failed/);
  assert.match(failing, /rejected the key/);
});

test("without edit rights the controls are hidden and the reason is given", () => {
  const out = html({ model, status: "ok", canEdit: false });
  assert.match(out, /Only project admins can change this/);
  assert.doesNotMatch(out, /type="password"|Delete key and connection|Save probes/);
});

test("the estimate follows the budget ceiling", () => {
  assert.match(html({ model: { ...model, monthly_budget: 100 }, probes: [] }), /up to 100 calls a month/);
});

test("the page is dark: it 404s unless the cloudConnect flag is on, and never selects secret columns", () => {
  const page = readFileSync("app/dashboard/[projectId]/connect/page.tsx", "utf8");
  assert.match(page, /enabledFeatures\(\)\.has\("cloudConnect"\)/);
  assert.match(page, /notFound\(\)/);
  assert.ok(!/ciphertext|ephemeral|nonce|secret/i.test(page.replace(/\/\/.*$/gm, "")), "the page must not name any secret column");
  const actions = readFileSync("app/dashboard/connect-actions.ts", "utf8");
  assert.match(actions, /^"use server";/);
  assert.match(actions, /CONNECT_PUBLIC_KEY/);
  assert.ok(!/NEXT_PUBLIC_CONNECT|PRIVATE_KEY|RUNNER_SECRET/.test(actions), "the web tier must never hold the private key or the runner secret");
  assert.ok(!/console\.(log|error|warn)/.test(actions), "an action that sees a key must not log");
});
