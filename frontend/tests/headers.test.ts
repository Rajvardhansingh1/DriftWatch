import test from "node:test";
import assert from "node:assert/strict";
// @ts-expect-error next.config.js is untyped CommonJS
import nextConfig from "../next.config.js";

type Rule = { source: string; headers: { key: string; value: string }[] };

test("every route gets baseline security headers", async () => {
  const rules: Rule[] = await nextConfig.headers();
  const all = rules.find((r) => r.source === "/:path*")!;
  const keys = new Set(all.headers.map((h) => h.key));
  for (const k of ["Strict-Transport-Security", "X-Content-Type-Options", "Referrer-Policy",
                   "Permissions-Policy", "X-Frame-Options"]) {
    assert.ok(keys.has(k), `missing ${k}`);
  }
});

test("public CSP excludes app routes and forbids framing and plugins", async () => {
  const rules: Rule[] = await nextConfig.headers();
  const pub = rules.find((r) => r.headers.some((h) => h.key === "Content-Security-Policy"))!;
  assert.equal(pub.source, "/((?!(?:dashboard|admin|auth)(?:/|$)).*)");
  const csp = pub.headers.find((h) => h.key === "Content-Security-Policy")!.value;
  assert.match(csp, /frame-ancestors 'none'/);
  assert.match(csp, /object-src 'none'/);
});
