// DEV-ONLY: writes tests/fixtures/seal_v1.json, vectors sealed by Node for the Python tests to open.
//   node --import tsx scripts/make-seal-fixture.mjs
// The key pair below is generated here and used for nothing else. It protects only these made-up values.
import { generateKeyPairSync, randomUUID } from "node:crypto";
import { writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { sealSecret } from "../lib/connect/seal.ts";

const { publicKey, privateKey } = generateKeyPairSync("x25519");
const pub = publicKey.export({ format: "der", type: "spki" }).subarray(-32);
const priv = privateKey.export({ format: "der", type: "pkcs8" }).subarray(-32);
const samples = ["gsk_" + "a1B2c3D4e5F6".repeat(3), "sk-" + "Z9y8X7w6V5u4".repeat(4), "short-key-1", "x".repeat(512)];
const vectors = samples.map((plaintext, i) => {
  const model_id = randomUUID();
  return { plaintext, model_id, box: sealSecret(plaintext, model_id, i + 1, Buffer.from(pub).toString("base64")) };
});
const out = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "tests", "fixtures", "seal_v1.json");
const doc = {
  note: "Made by Node; the private key protects only these made-up values.",
  private_key: Buffer.from(priv).toString("base64"),
  public_key: Buffer.from(pub).toString("base64"),
  vectors,
};
writeFileSync(out, JSON.stringify(doc, null, 2) + "\n");
console.log("wrote", out);
