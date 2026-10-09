import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (p: string) => readFileSync(p, "utf8");

test("dashboard layout is dynamic, has Settings and a POST logout", () => {
  const src = read("app/dashboard/layout.tsx");
  assert.match(src, /export const dynamic = "force-dynamic"/);
  assert.match(src, /\/dashboard\/settings/);
  assert.match(src, /action="\/auth\/sign-out" method="post"/);
});

test("dashboard page lists projects through RLS and redirects when signed out", () => {
  const src = read("app/dashboard/page.tsx");
  assert.match(src, /listProjects\(/);
  assert.match(src, /redirect\("\/auth\/sign-in"\)/);
  assert.match(src, /CreateProjectForm/);
  assert.match(src, /auth\.getUser\(\)/);
  assert.doesNotMatch(src, /getSession\(/);
});

test("create project form is a client component calling the server action", () => {
  const src = read("components/console/CreateProjectForm.tsx");
  assert.match(src.trimStart(), /^"use client";/);
  assert.match(src, /createProject\(/);
  assert.match(src, /maxLength=\{64\}/);
  assert.match(src, /catch/);
  assert.match(src, /name="projectName"/);
  assert.match(src, /autoComplete="off"/);
});

test("dashboard error boundary is a client component that never prints error.message", () => {
  const src = read("app/dashboard/error.tsx");
  assert.match(src.trimStart(), /^"use client";/);
  assert.match(src, /reset/);
  assert.doesNotMatch(src, /error\.message/);
});
