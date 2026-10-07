import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import robots from "../app/robots";
import sitemap from "../app/sitemap";

test("sitemap lists public pages only", () => {
  const urls = sitemap().map((e) => new URL(e.url).pathname);
  assert.ok(urls.includes("/"));
  for (const hidden of ["/demo", "/dashboard", "/admin", "/auth/sign-in"]) assert.ok(!urls.includes(hidden), hidden);
});

test("robots keeps crawlers out of app routes and points at the sitemap", () => {
  const r = robots();
  const rule = Array.isArray(r.rules) ? r.rules[0] : r.rules;
  for (const p of ["/dashboard", "/admin", "/auth"]) assert.ok([rule.disallow].flat().includes(p), p);
  assert.ok(![rule.disallow].flat().includes("/demo"), "/demo must stay crawlable so noindex is seen");
  assert.match(String(r.sitemap), /\/sitemap\.xml$/);
});

test("llms.txt and security.txt exist with the required fields", () => {
  const llms = readFileSync("public/llms.txt", "utf8");
  assert.match(llms, /^# DriftWatch/m);
  const sec = readFileSync("public/.well-known/security.txt", "utf8");
  assert.match(sec, /^Contact: https:\/\//m);
  assert.match(sec, /^Expires: \d{4}-/m);
});
