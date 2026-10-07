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
