import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const visual = readFileSync("app/(marketing)/components/HeroVisual.tsx", "utf8");
const scene = readFileSync("app/(marketing)/components/HeroScene.tsx", "utf8");
const pkg = JSON.parse(readFileSync("package.json", "utf8"));

test("hero respects reduced motion and missing WebGL", () => {
  assert.match(visual, /prefers-reduced-motion: reduce/);
  assert.match(visual, /addEventListener\("change"/);
  assert.match(visual, /getContext\("webgl2"\)/);
  assert.match(visual, /hero-fallback\.svg/);
  assert.match(visual, /ssr: false/);
});

test("hero uses plain three.js, not fiber (fiber v8 breaks on Next 15's React)", () => {
  assert.equal(pkg.dependencies["@react-three/fiber"], undefined);
  assert.match(pkg.dependencies.three, /^\^?0\.169\./);
  assert.match(pkg.dependencies.react, /^\^?18\./);
  assert.match(scene, /from "three"/);
  assert.doesNotMatch(scene, /@react-three\/fiber/);
});

test("hero falls back to the static image when the WebGL context is lost", () => {
  assert.ok(scene.includes("webglcontextlost"));
  assert.ok(scene.includes('removeEventListener("webglcontextlost"'));
  assert.match(visual, /onContextLost=\{\(\) => setMode\("static"\)\}/);
});
