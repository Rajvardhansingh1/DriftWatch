import assert from "node:assert/strict";
import { generateKeyPairSync, randomUUID } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { SealError, sealSecret } from "../lib/connect/seal";

const pub = Buffer.from(generateKeyPairSync("x25519").publicKey.export({ format: "der", type: "spki" }).subarray(-32)).toString("base64");
const KEY = "gsk_" + "p".repeat(40);

test("a sealed key has the documented shape and never contains the key", () => {
  const box = sealSecret(KEY, randomUUID(), 1, pub);
  assert.deepEqual(Object.keys(box).sort(), ["ciphertext", "ephemeral", "key_id", "nonce"]);
  assert.equal(Buffer.from(box.ephemeral, "base64").length, 32);
  assert.equal(Buffer.from(box.nonce, "base64").length, 12);
  assert.equal(Buffer.from(box.ciphertext, "base64").length, KEY.length + 16);
  assert.ok(!JSON.stringify(box).includes(KEY) && !Buffer.from(box.ciphertext, "base64").includes(Buffer.from(KEY)));
});

test("every seal is different", () => {
  const id = randomUUID();
  const a = sealSecret(KEY, id, 1, pub);
  const b = sealSecret(KEY, id, 1, pub);
  assert.notEqual(a.ciphertext, b.ciphertext);
  assert.notEqual(a.ephemeral, b.ephemeral);
});

test("bad inputs are refused without echoing the key", () => {
  const id = randomUUID();
  for (const bad of ["", "x".repeat(513)]) assert.throws(() => sealSecret(bad, id, 1, pub), SealError);
  assert.throws(() => sealSecret(KEY, "not-a-uuid", 1, pub), SealError);
  for (const k of [0, 1001, 1.5, Number.NaN]) assert.throws(() => sealSecret(KEY, id, k, pub), SealError);
  assert.throws(() => sealSecret(KEY, id, 1, "AAAA"), SealError);
  try {
    sealSecret(KEY, "bad", 1, pub);
  } catch (e) {
    assert.ok(!String((e as Error).message).includes(KEY));
  }
});

test("the sealing module is never imported by client code", () => {
  const walk = (d: string): string[] =>
    readdirSync(d, { withFileTypes: true }).flatMap((e) => (e.isDirectory() ? walk(join(d, e.name)) : [join(d, e.name)]));
  for (const f of [...walk("app"), ...walk("components")].filter((p) => /\.(ts|tsx)$/.test(p))) {
    const src = readFileSync(f, "utf8");
    if (/connect\/seal/.test(src)) {
      assert.ok(!/^\s*["']use client["']/m.test(src), `${f} is a client file and imports the sealing module`);
      assert.ok(/(actions?|route|page)\.tsx?$|\/actions\//.test(f.split("\\").join("/")), `${f} should be a server action, route or page`);
    }
  }
});
