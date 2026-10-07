"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { createProject } from "@/app/dashboard/actions";

export function CreateProjectForm() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await createProject(name);
      if (!result.ok) {
        setError(result.error);
        setBusy(false);
        return;
      }
      // stay busy until navigation so a double click cannot create two projects
      router.push(`/dashboard/${result.id}`);
    } catch {
      setError("Could not create the project. Check your connection and try again.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-wrap items-end gap-3">
      <label className="flex flex-col gap-1 text-xs text-dim">
        Project name
        <input
          name="projectName"
          autoComplete="off"
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={64}
          required
          className="w-64 rounded border border-line bg-panel px-3 py-2 text-sm text-text"
          placeholder="My LLM app"
        />
      </label>
      <button disabled={busy} className="rounded bg-stable px-4 py-2 text-sm font-medium text-bg disabled:opacity-50">
        {busy ? "Creating..." : "Create project"}
      </button>
      {error && <p role="alert" className="w-full text-sm text-alert">{error}</p>}
    </form>
  );
}
