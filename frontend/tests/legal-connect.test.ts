import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const read = (page: string) => readFileSync(`app/(marketing)/${page}/page.tsx`, "utf8");
const GATE = 'enabledFeatures().has("cloudConnect")';

test("connected-model wording on privacy and terms appears only when the cloudConnect flag is on", () => {
  for (const page of ["privacy", "terms"]) {
    assert.ok(read(page).includes(GATE), `${page} gates the wording`);
  }
  for (const page of ["privacy", "terms"]) {
    const src = read(page);
    const outside = src.slice(0, src.indexOf(GATE)); // everything before the gated block
    assert.ok(!/connect a model|connected model/i.test(outside), `${page} has connected-model wording outside the gate`);
  }
});

test("the privacy wording says what is stored, who can read it, and how to delete it", () => {
  const src = read("privacy");
  for (const phrase of ["encrypted with a key that only our scheduled runner holds", "last four characters", "never the answers", "delete all of it", "billed by your provider"]) {
    assert.ok(src.includes(phrase), phrase);
  }
});
