// Pure helpers for the CLI device-login approval page. Mirrors 0009_device_auth.sql.

// 20 consonants: no vowels (no words), no 0/O/1/I.
export const USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ";
const CODE_RE = /^[BCDFGHJKLMNPQRSTVWXZ]{8}$/;

export function normalizeUserCode(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const code = raw.toUpperCase().replace(/[\s-]/g, "");
  return CODE_RE.test(code) ? code : null;
}

export function formatUserCode(code: string): string {
  return `${code.slice(0, 4)}-${code.slice(4)}`;
}

export interface DeviceRequest {
  deviceName: string;
  deviceOs: string;
  requestedAt: string;
}

// The device chose its own name, so treat it as untrusted text: no control
// characters, single spaces, at most 64 characters. React escapes it on render.
export function cleanDeviceText(raw: unknown): string {
  if (typeof raw !== "string") return "";
  // eslint-disable-next-line no-control-regex
  return raw.replace(/[\u0000-\u001f\u007f]+/g, " ").replace(/\s+/g, " ").trim().slice(0, 64);
}
