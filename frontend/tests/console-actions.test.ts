import test from "node:test";
import assert from "node:assert/strict";
import {
  createKeyCore, createProjectCore, deleteAccountCore, friendlyError, revokeKeyCore,
} from "../lib/console/actions-core";

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
const KEY = "dw_" + "a".repeat(10) + "_" + "b".repeat(64);

test("friendlyError shows our PT422 text, fixed sentences for the rest, never raw database text", () => {
  assert.equal(friendlyError({ code: "PT422", message: "project limit reached" }), "project limit reached");
  assert.match(friendlyError({ code: "PT401", message: "x" }), /sign in/i);
  assert.match(friendlyError({ code: "PT403", message: "x" }), /email|access/i);
  const generic = friendlyError({ code: "42P01", message: 'relation "secret_table" does not exist' });
  assert.doesNotMatch(generic, /secret_table/);
  assert.match(friendlyError({ code: "PT422", message: "x".repeat(500) }), /not accepted/i);
});

test("createProject validates, trims and returns the new id", async () => {
  const f = fake({ data: { id: PROJECT } });
  const r = await createProjectCore(f.client, "  My   app ");
  assert.deepEqual(r, { ok: true, id: PROJECT });
  assert.deepEqual(f.calls, [{ fn: "create_project", args: { p_name: "My app" } }]);
  const bad = await createProjectCore(f.client, "   ");
  assert.equal(bad.ok, false);
  assert.equal(f.calls.length, 1); // no RPC for invalid input
});

test("createProject surfaces the limit message from our SQL", async () => {
  const f = fake({ error: { code: "PT422", message: "project limit reached" } });
  assert.deepEqual(await createProjectCore(f.client, "x"), { ok: false, error: "project limit reached" });
});

test("createKey validates the uuid and name, returns the key once, rejects a malformed key", async () => {
  const f = fake({ data: KEY });
  const r = await createKeyCore(f.client, PROJECT, "laptop");
  assert.deepEqual(r, { ok: true, key: KEY });
  assert.deepEqual(f.calls[0], { fn: "create_project_api_key", args: { p_project_id: PROJECT, p_name: "laptop" } });
  assert.equal((await createKeyCore(f.client, "not-a-uuid", "laptop")).ok, false);
  assert.equal((await createKeyCore(f.client, PROJECT, "")).ok, false);
  assert.equal(f.calls.length, 1);
  const weird = fake({ data: "not-a-key" });
  const w = await createKeyCore(weird.client, PROJECT, "laptop");
  assert.equal(w.ok, false);
  assert.doesNotMatch(JSON.stringify(w), /not-a-key/);
});

test("createKey errors never echo the key or raw database messages", async () => {
  const f = fake({ error: { code: "XX000", message: `boom ${KEY}` } });
  const r = await createKeyCore(f.client, PROJECT, "laptop");
  assert.equal(r.ok, false);
  assert.doesNotMatch(JSON.stringify(r), /dw_/);
});

test("revokeKey checks the uuid then calls the RPC", async () => {
  const f = fake({});
  assert.equal((await revokeKeyCore(f.client, "nope")).ok, false);
  assert.deepEqual(await revokeKeyCore(f.client, PROJECT), { ok: true });
  assert.deepEqual(f.calls, [{ fn: "revoke_project_api_key", args: { p_key_id: PROJECT } }]);
});

test("deleteAccount needs the typed email to match the session email", async () => {
  const f = fake({});
  const wrong = await deleteAccountCore(f.client, "other@example.com", "me@example.com");
  assert.equal(wrong.ok, false);
  assert.equal(f.calls.length, 0);
  assert.equal((await deleteAccountCore(f.client, "", "me@example.com")).ok, false);
  assert.equal((await deleteAccountCore(f.client, "me@example.com", undefined)).ok, false);
  assert.deepEqual(await deleteAccountCore(f.client, "  ME@example.com ", "me@example.com"), { ok: true });
  assert.deepEqual(f.calls, [{ fn: "delete_my_account", args: undefined }]);
});

test("actions.ts is a server-actions module and never logs", async () => {
  const { readFileSync } = await import("node:fs");
  const src = readFileSync("app/dashboard/actions.ts", "utf8");
  assert.match(src.trimStart(), /^"use server";/);
  assert.doesNotMatch(src, /console\./);
  assert.doesNotMatch(readFileSync("lib/console/actions-core.ts", "utf8"), /console\./);
});
