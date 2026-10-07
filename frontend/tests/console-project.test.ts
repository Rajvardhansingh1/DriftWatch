import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { SyncChip } from "../components/SyncChip";

test("SyncChip renders each state with an accessible label", () => {
  for (const [state, text] of [
    ["live", "Live"], ["connecting", "Connecting"], ["offline", "Offline"],
    ["synced", "Synced"], ["pending", "pending"], ["paused", "Paused"],
  ] as const) {
    const html = renderToStaticMarkup(createElement(SyncChip, { state, detail: state === "pending" ? "3" : undefined }));
    assert.match(html, new RegExp(text, "i"), state);
    assert.match(html, /role="status"/);
  }
});

test("project page validates the id, uses RLS (notFound on miss) and a safe range", () => {
  const src = readFileSync("app/dashboard/[projectId]/page.tsx", "utf8");
  assert.match(src, /isUuid\(/);
  assert.match(src, /notFound\(\)/);
  assert.match(src, /parseRange\(/);
  assert.match(src, /loadSeries\(/);
});

test("ProjectLive subscribes only for live ranges and cleans up", () => {
  const src = readFileSync("components/console/ProjectLive.tsx", "utf8");
  assert.match(src.trimStart(), /^"use client";/);
  assert.match(src, /isLiveRange\(/);
  assert.match(src, /subscribeToProject\(/);
  assert.match(src, /return \(\) =>/); // effect cleanup
  assert.match(src, /COMBINED_PANEL/);
});

test("project page checks the user itself, in order: id, client, getUser, query", () => {
  const src = readFileSync("app/dashboard/[projectId]/page.tsx", "utf8");
  assert.match(src, /auth\.getUser\(\)/);
  assert.doesNotMatch(src, /getSession\(/);
  const i = (s: string) => src.indexOf(s);
  assert.ok(i("isUuid(") < i("createServerSupabase("));
  assert.ok(i("createServerSupabase(") < i("auth.getUser()"));
  assert.ok(i("auth.getUser()") < i("getProject("));
});

test("ProjectLive resets status to connecting on resubscribe", () => {
  assert.match(readFileSync("components/console/ProjectLive.tsx", "utf8"), /setStatus\("connecting"\)/);
});
