"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getSupabaseClient, isCloudAuthConfigured } from "../../lib/supabase";

// Display-only. Authorization is enforced by the monitor's /api/admin/status
// (allowlist check); hiding this page is not a control.
const MONITOR = process.env.NEXT_PUBLIC_MONITOR_API_URL ?? "http://localhost:8000";

type State =
  | { kind: "loading" }
  | { kind: "not-configured" }
  | { kind: "signed-out" }
  | { kind: "denied"; code: number }
  | { kind: "ok" };

export default function AdminPage() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    if (!isCloudAuthConfigured()) {
      setState({ kind: "not-configured" });
      return;
    }
    (async () => {
      const { data } = await getSupabaseClient()!.auth.getSession();
      const token = data.session?.access_token;
      if (!token) {
        setState({ kind: "signed-out" });
        return;
      }
      const resp = await fetch(`${MONITOR}/api/admin/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setState(resp.ok ? { kind: "ok" } : { kind: "denied", code: resp.status });
    })().catch(() => setState({ kind: "denied", code: 0 }));
  }, []);

  return (
    <main className="mx-auto max-w-md p-8 font-[var(--font-plex-sans)]">
      <h1 className="text-lg font-semibold">Operations</h1>
      {state.kind === "loading" && <p className="mt-3 text-sm text-neutral-400">Checking access...</p>}
      {state.kind === "not-configured" && (
        <p className="mt-3 text-sm text-neutral-400">Cloud auth is not configured for this deployment.</p>
      )}
      {state.kind === "signed-out" && (
        <p className="mt-3 text-sm">
          <Link href="/auth/sign-in" className="underline">Sign in</Link> to continue.
        </p>
      )}
      {state.kind === "denied" && (
        <p className="mt-3 text-sm text-red-400">
          Access denied{state.code ? ` (HTTP ${state.code})` : ""}. Platform operator access only.
        </p>
      )}
      {state.kind === "ok" && (
        <p className="mt-3 text-sm text-emerald-400">Platform operator access confirmed.</p>
      )}
    </main>
  );
}
