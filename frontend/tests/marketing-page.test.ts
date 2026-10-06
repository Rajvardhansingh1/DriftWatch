import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const read = (p: string) => readFileSync(p.replace(/^\.\.\//, ""), "utf8");

test("root redirect is gone and the marketing page owns /", () => {
  assert.equal(existsSync("app/page.tsx"), false);
  assert.ok(existsSync("app/(marketing)/page.tsx"));
});

test("nav has Demo, Log in and Sign up", () => {
  const nav = read("../app/(marketing)/components/Nav.tsx");
  for (const href of ['"/demo"', '"/auth/sign-in"', '"/auth/sign-up"']) assert.ok(nav.includes(href), href);
});

test("later scope only in the Coming soon section, never as inline badges", () => {
  const page = read("../app/(marketing)/page.tsx");
  assert.ok(page.includes("<ComingSoonSection items={upcoming} />"));
  assert.ok(!/<ComingSoon\s*\/>/.test(page), "inline Coming soon badge found");
  assert.match(read("../app/(marketing)/components/ComingSoonSection.tsx"), /id="coming-soon"/);
});

test("skeleton is announced to screen readers", () => {
  assert.match(read("../app/(marketing)/components/Skeleton.tsx"), /role="status"/);
});
