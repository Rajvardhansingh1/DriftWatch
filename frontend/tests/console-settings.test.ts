import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("export route is session-checked, no-store and an attachment", () => {
  const src = readFileSync("app/dashboard/settings/export/route.ts", "utf8");
  assert.match(src, /auth\.getUser\(\)/);
  assert.match(src, /status: 401/);
  assert.match(src, /export_my_data/);
  assert.match(src, /no-store/);
  assert.match(src, /attachment; filename="driftwatch-export\.json"/);
  assert.doesNotMatch(src, /console\./);
});

test("account danger zone requires the typed email and then leaves the console", () => {
  const src = readFileSync("components/console/AccountDanger.tsx", "utf8");
  assert.match(src.trimStart(), /^"use client";/);
  assert.match(src, /deleteAccount\(/);
  assert.match(src, /window\.location\.assign\("\/"\)/);
  assert.match(src, /disabled=\{busy \|\| typed\.trim\(\)\.length === 0\}/);
  assert.match(src, /catch \{/);
});

test("settings page shows the signed-in email and links the export", () => {
  const src = readFileSync("app/dashboard/settings/page.tsx", "utf8");
  assert.match(src, /\/dashboard\/settings\/export/);
  assert.match(src, /AccountDanger/);
  assert.match(src, /auth\.getUser\(\)/);
  assert.doesNotMatch(src, /getSession\(/);
});
