import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { toSeries } from "../local/api";
import { View, type ViewProps } from "../local/View";

const base: ViewProps = {
  projects: ["11111111-2222-4333-8444-555555555555"],
  project: "11111111-2222-4333-8444-555555555555",
  range: "24h",
  series: toSeries(null),
  status: { sync: { state: "synced", pending: 0 } },
  embedder: "ready",
  signedIn: true,
  error: null,
};
const html = (p: Partial<ViewProps>) => renderToStaticMarkup(React.createElement(View, { ...base, ...p }));

test("before sign-in the page explains how to open it, and shows no data", () => {
  const out = html({ signedIn: false });
  assert.match(out, /driftwatch dashboard/);
  assert.doesNotMatch(out, /Synced|embedding drift/);
});

test("an expired or wrong link shows the error instead", () => {
  assert.match(html({ signedIn: false, error: "That link did not work." }), /That link did not work/);
});

test("with no values yet it says what to expect and still draws the two signals the agent measures", () => {
  const out = html({});
  assert.match(out, /No drift values in this range yet/);
  assert.match(out, /embedding drift/);
  assert.match(out, /combined drift score/);
  assert.doesNotMatch(out, /canary accuracy|judge trend|hallucination/); // the agent does not measure these on its own
});

test("values are shown and a signal that has data appears even if the agent does not usually send it", () => {
  const series = toSeries({
    embedding_drift: [{ timestamp: "2026-10-13T10:00:00+00:00", value: 0.123 }],
    judge_trend: [{ timestamp: "2026-10-13T10:00:00+00:00", value: 0.8 }],
  });
  const out = html({ series });
  assert.doesNotMatch(out, /No drift values/);
  assert.match(out, /0\.123/);
  assert.match(out, /judge trend/);
});

test("the sync chip follows the agent: pending shows the count, a failed read shows offline", () => {
  assert.match(html({ status: { sync: { state: "pending", pending: 7 } } }), /7 pending/);
  assert.match(html({ status: null }), /Offline/);
  assert.match(html({}), /Synced/);
});

test("a model that is still loading is explained", () => {
  assert.match(html({ embedder: "loading" }), /The model is loading/);
});

test("with several projects there is a selector; with one there is not", () => {
  assert.match(html({ projects: ["a", "b"], project: "a" }), /<select/);
  assert.doesNotMatch(html({}), /<select/);
});

test("the local page never imports Supabase or the website's server code", () => {
  for (const f of readdirSync(join(__dirname, "..", "local")).filter((n) => /\.(ts|tsx)$/.test(n))) {
    const src = readFileSync(join(__dirname, "..", "local", f), "utf8");
    assert.doesNotMatch(src, /supabase|next\/|lib\/console/, f);
  }
  for (const f of ["SignalChart.tsx", "SyncChip.tsx"]) {
    const src = readFileSync(join(__dirname, "..", "components", f), "utf8");
    assert.doesNotMatch(src, /supabase|next\//, f);
  }
});
