"use server";

import { revalidatePath } from "next/cache";
import { createServerSupabase } from "@/lib/supabase/server";
import {
  approveDeviceCore, createKeyCore, createProjectCore, deleteAccountCore, denyDeviceCore,
  inspectDeviceCore, revokeKeyCore, type ActionResult,
} from "@/lib/console/actions-core";
import type { DeviceRequest } from "@/lib/console/device";

async function authed() {
  const supabase = await createServerSupabase();
  if (!supabase) return null;
  const { data } = await supabase.auth.getUser(); // server-validated, never getSession()
  return data.user ? { supabase, user: data.user } : null;
}

const SIGN_IN = { ok: false, error: "Please sign in again." } as const;

export async function createProject(rawName: string): Promise<ActionResult<{ id: string }>> {
  const a = await authed();
  if (!a) return SIGN_IN;
  const r = await createProjectCore(a.supabase, rawName);
  if (r.ok) revalidatePath("/dashboard");
  return r;
}

export async function createApiKey(projectId: string, rawName: string): Promise<ActionResult<{ key: string }>> {
  const a = await authed();
  if (!a) return SIGN_IN;
  return createKeyCore(a.supabase, projectId, rawName); // the key travels only in this response
}

export async function revokeApiKey(keyId: string): Promise<ActionResult> {
  const a = await authed();
  if (!a) return SIGN_IN;
  const r = await revokeKeyCore(a.supabase, keyId);
  if (r.ok) revalidatePath("/dashboard", "layout");
  return r;
}

export async function deleteAccount(typedEmail: string): Promise<ActionResult> {
  const a = await authed();
  if (!a) return SIGN_IN;
  const r = await deleteAccountCore(a.supabase, typedEmail, a.user.email);
  if (r.ok) {
    try {
      await a.supabase.auth.signOut({ scope: "global" });
    } catch {
      // signOut removes the session even if the user row is already gone; the client then navigates away.
    }
  }
  return r;
}

// CLI device login. Server actions only accept same-origin POSTs, which is the CSRF
// protection the approval needs; the RPCs run as the signed-in user.
export async function inspectDevice(
  rawCode: string,
): Promise<ActionResult<{ code: string; device: DeviceRequest }>> {
  const a = await authed();
  if (!a) return SIGN_IN;
  return inspectDeviceCore(a.supabase, rawCode);
}

export async function approveDevice(rawCode: string, projectId: string, confirmed: boolean): Promise<ActionResult> {
  const a = await authed();
  if (!a) return SIGN_IN;
  return approveDeviceCore(a.supabase, rawCode, projectId, confirmed);
}

export async function denyDevice(rawCode: string): Promise<ActionResult> {
  const a = await authed();
  if (!a) return SIGN_IN;
  return denyDeviceCore(a.supabase, rawCode);
}
