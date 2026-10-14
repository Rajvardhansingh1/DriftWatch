"use server";

import { randomUUID } from "node:crypto";
import { revalidatePath } from "next/cache";
import type { ActionResult } from "@/lib/console/actions-core";
import {
  connectModelCore, deleteConnectionCore, setProbesCore, updateConnectionCore, validateProviderKey, type ConnectDeps,
} from "@/lib/connect/core";
import { sealSecret } from "@/lib/connect/seal";
import { enabledFeatures } from "@/lib/features";
import { createServerSupabase } from "@/lib/supabase/server";

// Cloud connect server actions. Server actions accept only same-origin POSTs (the CSRF protection), and every RPC runs
// as the signed-in user, so the database decides who may do what. The provider key enters here and leaves sealed.
async function authed() {
  const supabase = await createServerSupabase();
  if (!supabase) return null;
  const { data } = await supabase.auth.getUser(); // server-validated, never getSession()
  return data.user ? { supabase } : null;
}

const SIGN_IN = { ok: false, error: "Please sign in again." } as const;
const OFF = { ok: false, error: "Cloud connect is not available right now." } as const;
const on = () => enabledFeatures().has("cloudConnect");

function deps(): ConnectDeps {
  return {
    enabled: on(),
    publicKey: process.env.CONNECT_PUBLIC_KEY ?? "", // server-only: the runner's PUBLIC key, which can only seal
    keyId: Number(process.env.CONNECT_KEY_ID ?? "1"),
    newId: () => randomUUID(),
    check: (provider, model, key) => validateProviderKey(fetch, provider, model, key),
    seal: sealSecret,
  };
}

export async function connectModel(projectId: string, input: unknown): Promise<ActionResult<{ last4: string }>> {
  const a = await authed();
  if (!a) return SIGN_IN;
  const r = await connectModelCore(a.supabase, deps(), projectId, input);
  if (r.ok) revalidatePath(`/dashboard/${projectId}/connect`);
  return r;
}

export async function saveProbes(projectId: string, probes: unknown): Promise<ActionResult> {
  const a = await authed();
  if (!a) return SIGN_IN;
  if (!on()) return OFF;
  const r = await setProbesCore(a.supabase, projectId, probes);
  if (r.ok) revalidatePath(`/dashboard/${projectId}/connect`);
  return r;
}

export async function saveConnection(projectId: string, settings: { intervalMinutes: unknown; monthlyBudget: unknown; enabled: unknown }): Promise<ActionResult> {
  const a = await authed();
  if (!a) return SIGN_IN;
  if (!on()) return OFF;
  const r = await updateConnectionCore(a.supabase, projectId, settings);
  if (r.ok) revalidatePath(`/dashboard/${projectId}/connect`);
  return r;
}

export async function removeConnection(projectId: string): Promise<ActionResult> {
  const a = await authed();
  if (!a) return SIGN_IN;
  const r = await deleteConnectionCore(a.supabase, projectId); // deleting stays possible even if the feature is switched off
  if (r.ok) revalidatePath(`/dashboard/${projectId}/connect`);
  return r;
}
