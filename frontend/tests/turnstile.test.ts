import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const widget = readFileSync("components/Turnstile.tsx", "utf8");
const pages = ["sign-in", "sign-up"].map((p) => [p, readFileSync(`app/auth/${p}/page.tsx`, "utf8")] as const);

test("Turnstile clears its token on expiry/error and can be reset", () => {
  assert.ok(widget.includes("expired-callback"));
  assert.ok(widget.includes("error-callback"));
  assert.ok(widget.includes("reset("));
  assert.ok(widget.includes("remove("));
});

for (const [name, src] of pages) {
  test(`${name} resets the widget and clears the token after a failed submit`, () => {
    assert.match(src, /resetKey=\{/);
    assert.match(src, /setCaptchaToken\(undefined\)/);
    assert.match(src, /Back to home/);
  });
}

test("sign-up requires 10 characters like Supabase and says so", () => {
  const src = pages.find(([n]) => n === "sign-up")![1];
  assert.ok(src.includes("minLength={10}"));
  assert.ok(src.includes("At least 10 characters"));
});
