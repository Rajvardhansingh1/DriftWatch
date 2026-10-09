import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (page: string) => readFileSync(`app/(marketing)/${page}/page.tsx`, "utf8");

for (const page of ["privacy", "terms", "data-deletion"]) {
  test(`${page} page exists and has a last-updated date`, () => {
    assert.match(read(page), /Last updated: \d{4}-\d{2}-\d{2}/);
  });
}

test("data-deletion describes self-serve deletion with a mailto fallback", () => {
  const src = read("data-deletion");
  assert.ok(src.includes("Settings"));
  assert.ok(src.includes("Delete account"));
  assert.ok(src.includes("security.txt") || src.includes("mailto:singh.rajvardhan.it@gmail.com"));
});

test("terms does not mention an allowance", () => {
  assert.ok(!/allowance/i.test(read("terms")));
});

for (const page of ["privacy", "terms", "data-deletion"]) {
  test(`${page} keeps the OG image and type in its own openGraph`, () => {
    const src = read(page);
    assert.ok(src.includes("og.png"));
    assert.ok(src.includes('type: "website"'));
  });
}

test("privacy names the sign-in cookies accurately", () => {
  const src = read("privacy");
  assert.ok(src.includes("short-lived sign-in verifier"));
  assert.ok(!src.includes("The only cookie"));
  assert.match(src, /no third-party analytics/);
});

test("privacy does not call live features not live", () => {
  const src = read("privacy");
  assert.ok(!src.includes("These features are not live yet"));
  assert.ok(src.includes("local agent is not available yet"));
});

test("privacy discloses the key prefix and what remains in the security log", () => {
  const src = read("privacy");
  assert.ok(src.includes("a short display prefix of the key"));
  assert.ok(src.includes("Earlier log entries keep a random identifier that no longer links to you after you delete your account."));
  assert.ok(!read("data-deletion").includes("download all your data"));
});
