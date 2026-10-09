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

test("nonce is forwarded to the page render and matches the response CSP", async () => {
  const res = await middleware(new NextRequest("http://localhost:3000/auth/sign-in"));
  const nonce = res.headers.get("x-middleware-request-x-nonce");
  assert.ok(nonce);
  assert.ok(res.headers.get("content-security-policy")!.includes(`'nonce-${nonce}'`));
});

for (const path of ["/dashboard", "/admin"]) {
  test(`configured env, no session cookie: ${path} redirects to sign-in`, async () => {
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://example.supabase.co";
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-test";
    try {
      const res = await middleware(new NextRequest(`http://localhost:3000${path}`));
      assert.equal(res.status, 307);
      assert.equal(new URL(res.headers.get("location")!).pathname, "/auth/sign-in");
    } finally {
      delete process.env.NEXT_PUBLIC_SUPABASE_URL;
      delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    }
  });
}

test("console CSP allows the Realtime websocket for https and plain-http (local) Supabase", async () => {
  for (const [url, ws] of [["https://example.supabase.co", "wss://example.supabase.co"], ["http://127.0.0.1:54321", "ws://127.0.0.1:54321"]]) {
    process.env.NEXT_PUBLIC_SUPABASE_URL = url;
    try {
      const res = await middleware(new NextRequest("http://localhost:3000/auth/sign-in"));
      const connect = res.headers.get("content-security-policy")!.split("; ").find((d) => d.startsWith("connect-src"))!;
      assert.ok(connect.split(" ").includes(ws), connect);
    } finally {
      delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    }
  }
});
