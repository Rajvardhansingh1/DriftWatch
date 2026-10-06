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

test("rejects embedded tab/CR/LF (WHATWG URL parser strips them)", () => {
  for (const bad of ["/\t/evil.example", "/\n/evil.example", "/\r/evil.example", "/\t\\evil.example"]) {
    assert.equal(safeNextPath(bad), "/dashboard", JSON.stringify(bad));
  }
});

test("encoded slash tricks stay on-origin", () => {
  for (const s of ["/%2F/evil.example", "/%5Cevil.example"]) {
    const out = safeNextPath(s);
    assert.ok(out.startsWith("/") && !out.startsWith("//"), out);
    assert.equal(new URL(out, "http://x.invalid").origin, "http://x.invalid");
  }
});
