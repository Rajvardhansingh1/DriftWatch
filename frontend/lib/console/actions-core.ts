import { cleanDeviceText, formatUserCode, normalizeUserCode, type DeviceRequest } from "./device";
import { isUuid, parseKeyName, parseProjectName } from "./validate";

export type ActionResult<T = object> = ({ ok: true } & T) | { ok: false; error: string };

export interface RpcError {
  code?: string;
  message?: string;
}
export interface RpcClient {
  rpc(
    fn: string,
    args?: Record<string, unknown>,
  ): PromiseLike<{ data: unknown; error: RpcError | null }>;
}

const FIXED: Record<string, string> = {
  PT401: "Please sign in again.",
  PT403: "You do not have access, or your email is not verified yet.",
  PT429: "Too many requests. Try again shortly.",
};

// Only PT422 messages are written by our own SQL and safe to show; everything
// else maps to a fixed sentence so database internals and keys never leak.
export function friendlyError(error: RpcError): string {
  const code = error.code ?? "";
  if (code === "PT422") {
    const m = error.message ?? "";
    return m.length > 0 && m.length <= 120 ? m : "That request was not accepted.";
  }
  return FIXED[code] ?? "Something went wrong. Please try again.";
}

const KEY_RE = /^dw_[0-9a-f]{10}_[0-9a-f]{64}$/;

export async function createProjectCore(client: RpcClient, rawName: unknown): Promise<ActionResult<{ id: string }>> {
  const name = parseProjectName(rawName);
  if (!name.ok) return { ok: false, error: name.error };
  const { data, error } = await client.rpc("create_project", { p_name: name.value });
  if (error) return { ok: false, error: friendlyError(error) };
  const id = (data as { id?: unknown } | null)?.id;
  if (!isUuid(id)) return { ok: false, error: "Something went wrong. Please try again." };
  return { ok: true, id };
}

export async function createKeyCore(
  client: RpcClient,
  projectId: unknown,
  rawName: unknown,
): Promise<ActionResult<{ key: string }>> {
  if (!isUuid(projectId)) return { ok: false, error: "Unknown project." };
  const name = parseKeyName(rawName);
  if (!name.ok) return { ok: false, error: name.error };
  const { data, error } = await client.rpc("create_project_api_key", {
    p_project_id: projectId,
    p_name: name.value,
  });
  if (error) return { ok: false, error: friendlyError(error) };
  if (typeof data !== "string" || !KEY_RE.test(data)) {
    return { ok: false, error: "Something went wrong. Please try again." };
  }
  return { ok: true, key: data };
}

export async function revokeKeyCore(client: RpcClient, keyId: unknown): Promise<ActionResult> {
  if (!isUuid(keyId)) return { ok: false, error: "Unknown key." };
  const { error } = await client.rpc("revoke_project_api_key", { p_key_id: keyId });
  return error ? { ok: false, error: friendlyError(error) } : { ok: true };
}

export async function deleteAccountCore(
  client: RpcClient,
  typedEmail: unknown,
  sessionEmail: string | undefined,
): Promise<ActionResult> {
  const typed = typeof typedEmail === "string" ? typedEmail.trim().toLowerCase() : "";
  if (!sessionEmail || typed === "" || typed !== sessionEmail.trim().toLowerCase()) {
    return { ok: false, error: "Type your account email exactly to confirm." };
  }
  const { error } = await client.rpc("delete_my_account");
  return error ? { ok: false, error: friendlyError(error) } : { ok: true };
}

const BAD_CODE_FORMAT = "Enter the 8-letter code shown in your terminal.";
const CODE_NOT_VALID = "That code is not valid or has expired.";
const LOCKED_OUT = "Too many wrong codes. Wait 15 minutes and try again.";

// PT429 here means the wrong-code lockout (or a start-rate cap), which deserves its own sentence.
function deviceError(error: RpcError): string {
  return error.code === "PT429" ? LOCKED_OUT : friendlyError(error);
}

function statusOf(data: unknown): string | null {
  const s = (data as { status?: unknown } | null)?.status;
  return typeof s === "string" ? s : null;
}

export async function inspectDeviceCore(
  client: RpcClient,
  rawCode: unknown,
): Promise<ActionResult<{ code: string; device: DeviceRequest }>> {
  const code = normalizeUserCode(rawCode);
  if (!code) return { ok: false, error: BAD_CODE_FORMAT };
  const { data, error } = await client.rpc("inspect_device_login", { p_user_code: code });
  if (error) return { ok: false, error: deviceError(error) };
  const status = statusOf(data);
  if (status === "invalid") return { ok: false, error: CODE_NOT_VALID };
  const d = data as { device_name?: unknown; device_os?: unknown; requested_at?: unknown };
  const deviceName = cleanDeviceText(d.device_name);
  const deviceOs = cleanDeviceText(d.device_os);
  const requestedAt = typeof d.requested_at === "string" && !Number.isNaN(Date.parse(d.requested_at)) ? d.requested_at : "";
  if (status !== "pending" || !deviceName || !deviceOs || !requestedAt) {
    return { ok: false, error: "Something went wrong. Please try again." };
  }
  return { ok: true, code: formatUserCode(code), device: { deviceName, deviceOs, requestedAt } };
}

export async function approveDeviceCore(
  client: RpcClient,
  rawCode: unknown,
  projectId: unknown,
  confirmed: unknown,
): Promise<ActionResult> {
  if (confirmed !== true) return { ok: false, error: "Tick the box to confirm you started this sign-in." };
  const code = normalizeUserCode(rawCode);
  if (!code) return { ok: false, error: BAD_CODE_FORMAT };
  if (!isUuid(projectId)) return { ok: false, error: "Choose a project." };
  const { data, error } = await client.rpc("approve_device_login", { p_user_code: code, p_project_id: projectId });
  if (error) return { ok: false, error: deviceError(error) };
  const status = statusOf(data);
  if (status === "invalid") return { ok: false, error: CODE_NOT_VALID };
  return status === "approved" ? { ok: true } : { ok: false, error: "Something went wrong. Please try again." };
}

export async function denyDeviceCore(client: RpcClient, rawCode: unknown): Promise<ActionResult> {
  const code = normalizeUserCode(rawCode);
  if (!code) return { ok: false, error: BAD_CODE_FORMAT };
  const { data, error } = await client.rpc("deny_device_login", { p_user_code: code });
  if (error) return { ok: false, error: deviceError(error) };
  const status = statusOf(data);
  if (status === "invalid") return { ok: false, error: CODE_NOT_VALID };
  return status === "denied" ? { ok: true } : { ok: false, error: "Something went wrong. Please try again." };
}
