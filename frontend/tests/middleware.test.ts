import test from "node:test";
import assert from "node:assert/strict";
import { NextRequest } from "next/server";
import { middleware } from "../middleware";

test("protected route fails closed when cloud auth is not configured", async () => {
  delete process.env.NEXT_PUBLIC_SUPABASE_URL;
  delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  const res = await middleware(new NextRequest("http://localhost:3000/dashboard"));
  assert.equal(res.status, 307);
  assert.equal(new URL(res.headers.get("location")!).pathname, "/auth/sign-in");
});

test("auth routes get a nonce CSP, Turnstile frames only, no unsafe-inline scripts", async () => {
  const res = await middleware(new NextRequest("http://localhost:3000/auth/sign-in"));
  const csp = res.headers.get("content-security-policy")!;
  assert.match(csp, /script-src 'self' 'nonce-[^']+' 'strict-dynamic'/);
  assert.doesNotMatch(csp, /script-src[^;]*'unsafe-inline'/);
  assert.match(csp, /frame-src https:\/\/challenges\.cloudflare\.com/);
  assert.match(csp, /frame-ancestors 'none'/);
});
