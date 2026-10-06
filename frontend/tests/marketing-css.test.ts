import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync("app/(marketing)/marketing.css", "utf8");
const TOKENS = ["--mk-bg", "--mk-surface", "--mk-fg", "--mk-muted", "--mk-line", "--mk-accent", "--mk-warn"];

test("tokens defined for light and dark themes", () => {
  const dark = css.split("@media (prefers-color-scheme: dark)")[1] ?? "";
  for (const t of TOKENS) {
    assert.ok(css.includes(`${t}:`), `light ${t}`);
    assert.ok(dark.includes(`${t}:`), `dark ${t}`);
  }
});

test("motion stops under reduced motion", () => {
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none/);
});
