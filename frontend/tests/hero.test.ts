import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const visual = readFileSync("app/(marketing)/components/HeroVisual.tsx", "utf8");
const pkg = JSON.parse(readFileSync("package.json", "utf8"));

test("hero respects reduced motion and missing WebGL", () => {
  assert.match(visual, /prefers-reduced-motion: reduce/);
  assert.match(visual, /getContext\("webgl2"\)/);
  assert.match(visual, /hero-fallback\.svg/);
  assert.match(visual, /ssr: false/);
});

test("fiber stays on v8 while the app is on React 18", () => {
  assert.match(pkg.dependencies["@react-three/fiber"], /^\^?8\./);
  assert.match(pkg.dependencies.react, /^\^?18\./);
});
