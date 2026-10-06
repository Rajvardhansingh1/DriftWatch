"use client";

import { useState } from "react";
import Link from "next/link";
import { getSupabaseClient, isCloudAuthConfigured } from "../../../lib/supabase";

export default function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "error" | "success">("idle");
  const [message, setMessage] = useState("");

  if (!isCloudAuthConfigured()) {
    return (
      <main className="mx-auto max-w-sm p-8 font-[var(--font-plex-sans)]">
        <h1 className="text-lg font-semibold">Cloud account sign-in</h1>
        <p className="mt-2 text-sm text-neutral-400">
          Cloud auth is not configured for this deployment. The local dashboard works fully
          without a cloud account. <Link href="/" className="underline">Back to dashboard</Link>
        </p>
      </main>
    );
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setStatus("loading");
    setMessage("");
    const supabase = getSupabaseClient()!;
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) {
      setStatus("error");
      setMessage(error.message);
      return;
    }
    setStatus("success");
    window.location.href = "/dashboard";
  }

  return (
    <main className="mx-auto max-w-sm p-8 font-[var(--font-plex-sans)]">
      <h1 className="text-lg font-semibold">Sign in</h1>
      <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-3">
        <input
          type="email"
          required
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
        />
        <input
          type="password"
          required
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="rounded border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={status === "loading"}
          className="rounded bg-emerald-600 px-3 py-2 text-sm font-medium disabled:opacity-50"
        >
          {status === "loading" ? "Signing in..." : "Sign in"}
        </button>
        {status === "error" && <p className="text-sm text-red-400">{message}</p>}
      </form>
      <p className="mt-4 text-sm text-neutral-400">
        No account? <Link href="/auth/sign-up" className="underline">Sign up</Link>
      </p>
    </main>
  );
}
