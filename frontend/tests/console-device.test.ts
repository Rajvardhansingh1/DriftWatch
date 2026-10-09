import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cleanDeviceText, formatUserCode, normalizeUserCode } from "../lib/console/device";
import { approveDeviceCore, denyDeviceCore, inspectDeviceCore } from "../lib/console/actions-core";

type Call = { fn: string; args: Record<string, unknown> | undefined };
function fake(reply: { data?: unknown; error?: { code?: string; message?: string } | null }) {
  const calls: Call[] = [];
  return {
    calls,
    client: {
      rpc: async (fn: string, args?: Record<string, unknown>) => {
        calls.push({ fn, args });
        return { data: reply.data ?? null, error: reply.error ?? null };
      },
    },
  };
}
const PROJECT = "11111111-1111-4111-8111-111111111111";
const PENDING = {
  status: "pending", device_name: "laptop", device_os: "Linux 6.1",
  requested_at: "2026-10-09T10:00:00Z", expires_at: "2026-10-09T10:10:00Z",
};

test("normalizeUserCode accepts dashes, spaces and lower case; rejects anything else", () => {
  for (const ok of ["BCDF-GHJK", "bcdf-ghjk", "BCDF GHJK", " bcdfghjk ", "BCDFGHJK"]) {
    assert.equal(normalizeUserCode(ok), "BCDFGHJK", ok);
  }
  for (const bad of ["BCDF-GHJA", "BCDF-GHJ0", "BCDFGHJ", "BCDFGHJKL", "", "----", 12345678, null, undefined, {}]) {
    assert.equal(normalizeUserCode(bad as unknown), null, String(bad));
  }
});

test("formatUserCode shows the code as XXXX-XXXX", () => {
  assert.equal(formatUserCode("BCDFGHJK"), "BCDF-GHJK");
});

test("cleanDeviceText strips control characters, collapses spaces and clips to 64", () => {
  assert.equal(cleanDeviceText("  my\u0007  \n laptop "), "my laptop");
  assert.equal(cleanDeviceText("x".repeat(200)).length, 64);
  assert.equal(cleanDeviceText(42 as unknown), "");
});

test("inspect normalises the code, calls the RPC and returns device facts only", async () => {
  const f = fake({ data: PENDING });
  const r = await inspectDeviceCore(f.client, "bcdf-ghjk");
  assert.deepEqual(f.calls, [{ fn: "inspect_device_login", args: { p_user_code: "BCDFGHJK" } }]);
  assert.deepEqual(r, {
    ok: true, code: "BCDF-GHJK",
    device: { deviceName: "laptop", deviceOs: "Linux 6.1", requestedAt: "2026-10-09T10:00:00Z" },
  });
});

test("inspect sanitises a hostile device name before it reaches the page", async () => {
  const f = fake({ data: { ...PENDING, device_name: "<b>x</b>\u0000\u001b[31m" + "y".repeat(100) } });
  const r = await inspectDeviceCore(f.client, "BCDFGHJK");
  assert.equal(r.ok, true);
  if (r.ok) {
    assert.ok(r.device.deviceName.length <= 64);
    assert.doesNotMatch(r.device.deviceName, /[\u0000-\u001f]/);
  }
});

test("inspect rejects a malformed code without calling the server", async () => {
  const f = fake({ data: PENDING });
  const r = await inspectDeviceCore(f.client, "hello");
  assert.deepEqual(r, { ok: false, error: "Enter the 8-letter code shown in your terminal." });
  assert.equal(f.calls.length, 0);
});

test("inspect maps invalid, lockout and unexpected replies to fixed sentences", async () => {
  const invalid = await inspectDeviceCore(fake({ data: { status: "invalid" } }).client, "BCDFGHJK");
  assert.deepEqual(invalid, { ok: false, error: "That code is not valid or has expired." });
  const locked = await inspectDeviceCore(fake({ error: { code: "PT429", message: "raw db text" } }).client, "BCDFGHJK");
  assert.equal(locked.ok, false);
  if (!locked.ok) {
    assert.match(locked.error, /wrong codes/i);
    assert.doesNotMatch(locked.error, /raw db text/);
  }
  const odd = await inspectDeviceCore(fake({ data: { status: "pending" } }).client, "BCDFGHJK");
  assert.equal(odd.ok, false); // pending without device facts is not trusted
  const unsigned = await inspectDeviceCore(fake({ error: { code: "PT401" } }).client, "BCDFGHJK");
  assert.match((unsigned as { error: string }).error, /sign in/i);
});

test("approve needs the checkbox, a uuid and a valid code before any RPC", async () => {
  const f = fake({ data: { status: "approved" } });
  assert.equal((await approveDeviceCore(f.client, "BCDFGHJK", PROJECT, false)).ok, false);
  assert.equal((await approveDeviceCore(f.client, "BCDFGHJK", PROJECT, "yes" as unknown)).ok, false);
  assert.equal((await approveDeviceCore(f.client, "BCDFGHJK", "not-a-uuid", true)).ok, false);
  assert.equal((await approveDeviceCore(f.client, "nope", PROJECT, true)).ok, false);
  assert.equal(f.calls.length, 0);
});

test("approve calls approve_device_login and only trusts an approved status", async () => {
  const f = fake({ data: { status: "approved" } });
  assert.deepEqual(await approveDeviceCore(f.client, "bcdf-ghjk", PROJECT, true), { ok: true });
  assert.deepEqual(f.calls, [{ fn: "approve_device_login", args: { p_user_code: "BCDFGHJK", p_project_id: PROJECT } }]);
  const invalid = await approveDeviceCore(fake({ data: { status: "invalid" } }).client, "BCDFGHJK", PROJECT, true);
  assert.deepEqual(invalid, { ok: false, error: "That code is not valid or has expired." });
  const forbidden = await approveDeviceCore(fake({ error: { code: "PT403" } }).client, "BCDFGHJK", PROJECT, true);
  assert.equal(forbidden.ok, false);
});

test("deny calls deny_device_login with the normalised code", async () => {
  const f = fake({ data: { status: "denied" } });
  assert.deepEqual(await denyDeviceCore(f.client, "bcdf ghjk"), { ok: true });
  assert.deepEqual(f.calls, [{ fn: "deny_device_login", args: { p_user_code: "BCDFGHJK" } }]);
  const invalid = await denyDeviceCore(fake({ data: { status: "invalid" } }).client, "BCDFGHJK");
  assert.equal(invalid.ok, false);
});

test("device server actions check the session first and stay server-side", () => {
  const src = readFileSync("app/dashboard/actions.ts", "utf8");
  assert.match(src.trimStart(), /^"use server";/);
  for (const name of ["inspectDevice", "approveDevice", "denyDevice"]) {
    const body = src.slice(src.indexOf(`export async function ${name}`));
    const head = body.slice(0, body.indexOf("\n}\n"));
    assert.match(head, /const a = await authed\(\)/, name);
    assert.ok(head.indexOf("authed()") < head.indexOf("Core("), `${name}: session check before the RPC`);
  }
  assert.doesNotMatch(src, /auth\.getSession\(/); // comments may mention it; calls may not
});
