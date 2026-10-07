import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (page: string) => readFileSync(`app/(marketing)/${page}/page.tsx`, "utf8");

for (const page of ["privacy", "terms", "data-deletion"]) {
  test(`${page} page exists and has a last-updated date`, () => {
    assert.match(read(page), /Last updated: \d{4}-\d{2}-\d{2}/);
  });
}

test("data-deletion does not promise a delete button and points at security.txt", () => {
  const src = read("data-deletion");
  assert.ok(!src.includes("choose Delete account"));
  assert.ok(src.includes("security.txt"));
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
