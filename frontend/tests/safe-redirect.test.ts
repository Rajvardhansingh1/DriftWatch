import test from "node:test";
import assert from "node:assert/strict";
import { safeNextPath } from "../lib/safe-redirect";

test("keeps same-site relative paths", () => {
  assert.equal(safeNextPath("/dashboard/keys"), "/dashboard/keys");
});

test("rejects absolute, protocol-relative and backslash tricks", () => {
  for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "", null]) {
    assert.equal(safeNextPath(bad), "/dashboard", String(bad));
  }
});
