import test from "node:test";
import assert from "node:assert/strict";
import { enabledFeatures, isLive } from "../lib/features";
import { FAQ, HERO, SITE, HOW_TO_STEPS, KEYS, MODES, ROADMAP, SIGNALS } from "../app/(marketing)/content";
import { buildLd, serializeLd } from "../lib/seo/jsonld";

const BANNED = [
  "seamless", "unlock", "leverage", "cutting-edge", "game-changer", "game changer", "revolution",
  "supercharge", "effortless", "robust", "delve", "elevate", "empower", "harness",
  "next-generation", "ai-powered", "in today's", "world-class", "—",
];

function allStrings(v: unknown): string[] {
  if (typeof v === "string") return [v];
  if (Array.isArray(v)) return v.flatMap(allStrings);
  if (v && typeof v === "object") return Object.values(v).flatMap(allStrings);
  return [];
}

test("copy avoids template phrases and invented percentages or multipliers", () => {
  for (const s of allStrings({ FAQ, HERO, HOW_TO_STEPS, KEYS, MODES, ROADMAP, SIGNALS })) {
    const lower = s.toLowerCase();
    for (const b of BANNED) assert.ok(!lower.includes(b), `"${b}" in: ${s}`);
    assert.doesNotMatch(s, /\d+(\.\d+)?\s?(%|x\b)/, `unsupported stat in: ${s}`);
  }
});

test("FAQ answers are 40-60 words (answer-engine friendly)", () => {
  for (const f of FAQ) {
    const words = f.answer.trim().split(/\s+/).length;
    assert.ok(words >= 40 && words <= 60, `${words} words: ${f.question}`);
  }
});

test("features parse from the env string and gate content", () => {
  const on = enabledFeatures("cli, freeKey,bogus");
  assert.deepEqual([...on].sort(), ["cli", "freeKey"]);
  assert.equal(isLive({ needs: ["cloudConnect"] }, on), false);
  assert.equal(isLive({}, on), true);
});

test("structured data only describes live features", () => {
  const none = buildLd(enabledFeatures(""), "https://example.test");
  assert.ok(!none.some((d: any) => d["@type"] === "HowTo"), "HowTo without CLI");
  const faq = none.find((d: any) => d["@type"] === "FAQPage") as any;
  const liveQs = FAQ.filter((f) => isLive(f, enabledFeatures(""))).map((f) => f.question);
  assert.deepEqual(faq.mainEntity.map((q: any) => q.name), liveQs);

  const cli = buildLd(enabledFeatures("cli"), "https://example.test");
  const howTo = cli.find((d: any) => d["@type"] === "HowTo") as any;
  assert.deepEqual(howTo.step.map((s: any) => s.name), HOW_TO_STEPS.map((s) => s.name));
});

test("Plan 1 content needs no later feature; later scope lives only in ROADMAP", () => {
  const none = enabledFeatures("");
  assert.ok(FAQ.filter((f) => isLive(f, none)).length >= 4, "enough live FAQ entries for Plan 1");
  assert.ok(ROADMAP.every((r) => !isLive(r, none)), "every roadmap item is later scope");
  const all = enabledFeatures("cli,freeKey,cloudConnect");
  assert.equal(ROADMAP.filter((r) => !isLive(r, all)).length, 0, "roadmap empties when everything ships");
});

test("operatingSystem reflects what is shipped", () => {
  const os = (raw: string) => (buildLd(enabledFeatures(raw), "https://example.test")[0] as any).operatingSystem;
  assert.equal(os(""), "Web");
  assert.equal(os("cli"), "Windows, macOS, Linux");
});

test("serializeLd cannot break out of the script tag", () => {
  const out = serializeLd({ x: "</script><script>alert(1)</script>&" });
  assert.ok(!out.includes("<") && !out.includes(">") && !out.includes("&"));
  assert.equal(JSON.parse(out).x, "</script><script>alert(1)</script>&");
});

test("meta description fits a search snippet", () => {
  assert.ok(SITE.description.length >= 120 && SITE.description.length <= 160, String(SITE.description.length));
});
