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
