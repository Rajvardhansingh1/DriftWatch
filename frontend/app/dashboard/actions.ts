"use server";

import { revalidatePath } from "next/cache";
import { createServerSupabase } from "@/lib/supabase/server";
import {
  createKeyCore, createProjectCore, deleteAccountCore, revokeKeyCore, type ActionResult,
} from "@/lib/console/actions-core";

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
      // The user row is already gone; the cookies are cleared by the redirect.
    }
  }
  return r;
}
