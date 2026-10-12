import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

test("e2e harness exists and is not imported by the app", () => {
  for (const f of ["fake-supabase.mjs", "run.mjs", "README.md"]) {
    assert.ok(existsSync(join("e2e", f)), f);
  }
  const walk = (d: string): string[] =>
    readdirSync(d, { withFileTypes: true }).flatMap((e) =>
      e.isDirectory() ? (e.name === "node_modules" || e.name === ".next" ? [] : walk(join(d, e.name))) : [join(d, e.name)],
    );
  for (const f of [...walk("app"), ...walk("lib"), ...walk("components")]) {
    assert.doesNotMatch(readFileSync(f, "utf8"), /e2e\/|fake-supabase/, f);
  }
});

test("harness fake covers the device-login RPCs and run.mjs checks the approval flow", () => {
  const fake = readFileSync(join("e2e", "fake-supabase.mjs"), "utf8");
  for (const rpc of [
    "start_device_login", "poll_device_login", "inspect_device_login", "approve_device_login", "deny_device_login",
  ]) {
    assert.ok(fake.includes(`"${rpc}"`), rpc);
  }
  // start/poll are the only RPCs callable without a session, as in 0009.
  assert.match(fake, /\["start_device_login", "poll_device_login"\]\.includes\(name\)/);
  const run = readFileSync(join("e2e", "run.mjs"), "utf8");
  for (const id of ["l1.", "l2.", "l3.", "l4."]) assert.ok(run.includes(`"${id}`), id);
});
