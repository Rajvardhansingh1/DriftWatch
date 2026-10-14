import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
// @ts-expect-error plain JS module
import { advisories, unaccepted } from "../scripts/audit-check.mjs";

const report = {
  vulnerabilities: {
    next: { severity: "moderate", via: ["postcss"] },
    postcss: {
      severity: "high",
      via: [
        { name: "postcss", severity: "high", title: "XSS", url: "https://github.com/advisories/GHSA-qx2v-qp2m-jg93" },
        { name: "postcss", severity: "moderate", title: "minor", url: "https://github.com/advisories/GHSA-minor-0000-0000" },
      ],
    },
    other: { severity: "critical", via: [{ name: "other", severity: "critical", title: "RCE", url: "https://github.com/advisories/GHSA-crit-1111-1111" }] },
  },
};
const NOW = new Date("2026-10-14T00:00:00Z");
const ex = (over: object = {}) => [{ id: "GHSA-qx2v-qp2m-jg93", reason: "not reachable", expires: "2026-12-31", ...over }];

test("advisories are read from objects, not from package-name strings", () => {
  assert.equal(advisories(report).length, 3);
  assert.deepEqual(advisories({}), []);
});

test("a serious advisory without an exception fails; a minor one does not", () => {
  const bad = unaccepted(report, [], NOW).map((a: { url: string }) => a.url.split("/").pop());
  assert.deepEqual(bad.sort(), ["GHSA-crit-1111-1111", "GHSA-qx2v-qp2m-jg93"]);
});

test("an exception with a reason and a future expiry accepts it", () => {
  const bad = unaccepted(report, ex(), NOW).map((a: { url: string }) => a.url.split("/").pop());
  assert.deepEqual(bad, ["GHSA-crit-1111-1111"]);
});

test("an expired exception, or one without a reason or date, no longer accepts it", () => {
  for (const over of [{ expires: "2026-10-01" }, { reason: "" }, { expires: undefined }]) {
    const bad = unaccepted(report, ex(over), NOW).map((a: { url: string }) => a.url.split("/").pop());
    assert.ok(bad.includes("GHSA-qx2v-qp2m-jg93"), JSON.stringify(over));
  }
});

test("every committed exception has an id, a reason and a date", () => {
  const doc = JSON.parse(readFileSync("../deploy/audit-exceptions.json", "utf8"));
  for (const e of doc.npm) {
    assert.match(e.id, /^GHSA-/);
    assert.ok(e.reason.length > 20 && /^\d{4}-\d{2}-\d{2}$/.test(e.expires), e.id);
  }
});
