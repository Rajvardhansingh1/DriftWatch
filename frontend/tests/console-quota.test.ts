import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AllowanceNote } from "../components/console/AllowanceNote";
import { parseQuota, quotaLine } from "../lib/console/quota";

test("parseQuota accepts the database's answer and nothing else", () => {
  assert.deepEqual(parseQuota({ used: 6, cap: 50, enabled: true }), { used: 6, cap: 50, enabled: true });
  for (const bad of [null, undefined, "x", [], {}, { used: "6", cap: 50, enabled: true }, { used: -1, cap: 50, enabled: true },
    { used: 1, cap: 50.5, enabled: true }, { used: 1, cap: 50 }, { used: Number.NaN, cap: 50, enabled: true }]) {
    assert.equal(parseQuota(bad), null);
  }
});

test("quotaLine says what is left in plain words", () => {
  assert.equal(quotaLine({ used: 6, cap: 50, enabled: true }), "6 of 50 judged responses used");
  assert.match(quotaLine({ used: 50, cap: 50, enabled: true }), /used up/i);
  assert.match(quotaLine({ used: 0, cap: 50, enabled: false }), /switched off/i);
  assert.match(quotaLine({ used: 60, cap: 50, enabled: true }), /^50 of 50/); // never shows more than the cap
});

test("the note shows the numbers, how to use the judge, and that nothing is stored by the relay", () => {
  const html = renderToStaticMarkup(React.createElement(AllowanceNote, { quota: { used: 6, cap: 50, enabled: true } }));
  assert.match(html, /Free allowance/);
  assert.match(html, /6 of 50/);
  assert.match(html, /driftwatch judge enable/);
  assert.match(html, /keeps nothing|does not keep/i);
  assert.match(html, /role="progressbar"|<progress/);
});

test("a used-up allowance points to the own-key route", () => {
  const html = renderToStaticMarkup(React.createElement(AllowanceNote, { quota: { used: 50, cap: 50, enabled: true } }));
  assert.match(html, /driftwatch key set/);
});
