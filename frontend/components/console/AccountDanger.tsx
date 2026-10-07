"use client";

import { useState } from "react";
import { deleteAccount } from "@/app/dashboard/actions";

export function AccountDanger({ email }: { email: string }) {
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await deleteAccount(typed);
      if (!result.ok) {
        setError(result.error);
        setBusy(false);
        return;
      }
      window.location.assign("/");
    } catch {
      setError("Could not delete the account. Check your connection and try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="rounded border border-alert/60 p-4">
      <h2 className="text-sm font-semibold text-alert">Delete account</h2>
      <p className="mt-2 max-w-xl text-sm text-dim">
        This permanently deletes your account, projects, API keys and scores. It cannot be undone. Export your
        data first if you want a copy. Type <span className="font-mono text-text">{email}</span> to confirm.
      </p>
      <input
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        autoComplete="off"
        aria-label="Type your email to confirm"
        className="mt-3 w-full max-w-sm rounded border border-line bg-panel px-3 py-2 text-sm text-text"
      />
      <div className="mt-3">
        <button
          disabled={busy || typed.trim().length === 0}
          className="rounded bg-alert px-4 py-2 text-sm font-medium text-bg disabled:opacity-50"
        >
          {busy ? "Deleting..." : "Delete my account"}
        </button>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-alert">{error}</p>}
    </form>
  );
}
