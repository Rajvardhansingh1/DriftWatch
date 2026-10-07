"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createApiKey, revokeApiKey } from "@/app/dashboard/actions";
import type { KeyRow } from "@/lib/console/data";

export function eventExample(apiBase: string, anonKey: string, apiKey: string): string {
  return [
    `curl -X POST ${apiBase}/rest/v1/rpc/ingest_event \\`,
    `  -H "apikey: ${anonKey}" \\`,
    `  -H "Content-Type: application/json" \\`,
    `  -d '{`,
    `    "p_api_key": "${apiKey}",`,
    `    "p_event": {`,
    `      "schema_version": 1,`,
    `      "event_id": "<a new uuid>",`,
    `      "occurred_at": "<now, ISO 8601 with Z>",`,
    `      "source": "my-app",`,
    `      "signal": "combined_score",`,
    `      "value": 0.12`,
    `    }`,
    `  }'`,
  ].join("\n");
}

export function KeyManager({
  projectId, keys, apiBase, anonKey,
}: { projectId: string; keys: KeyRow[]; apiBase: string; anonKey: string }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [created, setCreated] = useState<{ name: string; key: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await createApiKey(projectId, name);
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setCreated({ name, key: result.key }); // lives in memory only; refresh keeps this component mounted
      setName("");
      setCopied(false);
      router.refresh();
    } catch {
      setError("Could not create the key. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function onRevoke(id: string) {
    if (confirming !== id) {
      setConfirming(id);
      return;
    }
    setConfirming(null);
    try {
      const result = await revokeApiKey(id);
      if (!result.ok) setError(result.error);
      router.refresh();
    } catch {
      setError("Could not revoke the key. Try again.");
    }
  }

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div>
      {created && (
        <section aria-label="New API key" className="mb-8 rounded border border-drift bg-panel p-4">
          <p className="text-sm font-semibold">Key &quot;{created.name}&quot; created</p>
          <p className="mt-1 text-xs text-drift">Copy it now. It is shown once and cannot be shown again.</p>
          <code className="mt-3 block break-all rounded bg-bg px-3 py-2 font-mono text-xs">{created.key}</code>
          <div className="mt-3 flex gap-3">
            <button onClick={() => copy(created.key)} className="rounded border border-line px-3 py-1.5 text-sm hover:border-dim">
              {copied ? "Copied" : "Copy key"}
            </button>
            <button onClick={() => setCreated(null)} className="rounded bg-stable px-3 py-1.5 text-sm font-medium text-bg">
              I have saved it
            </button>
          </div>
          <details className="mt-4 text-xs text-dim">
            <summary className="cursor-pointer">Send a first event</summary>
            <pre className="mt-2 overflow-x-auto rounded bg-bg p-3 font-mono">{eventExample(apiBase, anonKey, created.key)}</pre>
          </details>
        </section>
      )}

      <form onSubmit={onCreate} className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-dim">
          Key name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={64}
            required
            placeholder="laptop"
            className="w-56 rounded border border-line bg-panel px-3 py-2 text-sm text-text"
          />
        </label>
        <button disabled={busy} className="rounded bg-stable px-4 py-2 text-sm font-medium text-bg disabled:opacity-50">
          {busy ? "Creating..." : "Create key"}
        </button>
      </form>
      {error && <p role="alert" className="mt-3 text-sm text-alert">{error}</p>}

      <h2 className="mt-10 text-sm font-semibold">Keys</h2>
      {keys.length === 0 ? (
        <p className="mt-2 text-sm text-dim">No keys yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-line rounded border border-line">
          {keys.map((k) => (
            <li key={k.id} className="flex flex-wrap items-center justify-between gap-3 p-3 text-sm">
              <div>
                <p className="font-medium">{k.name} {k.revoked_at && <span className="ml-1 text-xs text-alert">revoked</span>}</p>
                <p className="font-mono text-xs text-dim">
                  {k.prefix}_… created {new Date(k.created_at).toLocaleDateString("en-GB")}
                  {k.last_used_at ? `, last used ${new Date(k.last_used_at).toLocaleString("en-GB")}` : ", never used"}
                </p>
              </div>
              {!k.revoked_at && (
                <button onClick={() => onRevoke(k.id)} className="rounded border border-line px-3 py-1.5 text-xs hover:border-alert hover:text-alert">
                  {confirming === k.id ? "Click again to revoke" : "Revoke"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
