// Server-side only: seals a user's provider key with the runner's PUBLIC key (format v1, see monitor/cloud/seal.py).
// Only the runner holds the private key, so nothing the website stores can be decrypted by the website.
// Never import this from a client component: tests/connect-seal.test.ts enforces it.
import { createCipheriv, createPublicKey, diffieHellman, generateKeyPairSync, hkdfSync, randomBytes } from "node:crypto";

const TAG = Buffer.from("driftwatch-connect-v1");
const SPKI_X25519 = Buffer.from("302a300506032b656e032100", "hex"); // DER prefix for a raw 32-byte X25519 public key
const MAX_PLAINTEXT = 512;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type SealedBox = { key_id: number; ephemeral: string; nonce: string; ciphertext: string };

export class SealError extends Error {}

function keyIdBytes(keyId: number): Buffer {
  if (!Number.isInteger(keyId) || keyId < 1 || keyId > 1000) throw new SealError("bad key id");
  const b = Buffer.alloc(4);
  b.writeUInt32BE(keyId);
  return b;
}

export function sealSecret(plaintext: string, modelId: string, keyId: number, runnerPublicB64: string): SealedBox {
  if (typeof plaintext !== "string" || plaintext.length < 1 || plaintext.length > MAX_PLAINTEXT) throw new SealError("bad key");
  if (typeof modelId !== "string" || !UUID_RE.test(modelId)) throw new SealError("bad model id");
  const kid = keyIdBytes(keyId);
  const runnerRaw = Buffer.from(runnerPublicB64, "base64");
  if (runnerRaw.length !== 32) throw new SealError("bad runner key");
  const runnerPublic = createPublicKey({ key: Buffer.concat([SPKI_X25519, runnerRaw]), format: "der", type: "spki" });
  const { publicKey, privateKey } = generateKeyPairSync("x25519");
  const ephemeralPublic = publicKey.export({ format: "der", type: "spki" }).subarray(-32);
  const shared = diffieHellman({ privateKey, publicKey: runnerPublic });
  const key = Buffer.from(hkdfSync("sha256", shared, ephemeralPublic, Buffer.concat([TAG, kid]), 32));
  const nonce = randomBytes(12);
  const aad = Buffer.concat([TAG, Buffer.from(modelId.replace(/-/g, ""), "hex"), kid]);
  const cipher = createCipheriv("aes-256-gcm", key, nonce);
  cipher.setAAD(aad);
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final(), cipher.getAuthTag()]);
  return {
    key_id: keyId,
    ephemeral: Buffer.from(ephemeralPublic).toString("base64"),
    nonce: nonce.toString("base64"),
    ciphertext: ciphertext.toString("base64"),
  };
}
