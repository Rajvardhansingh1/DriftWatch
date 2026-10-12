"use client";

import { useState } from "react";
import { approveDevice, createProject, denyDevice, inspectDevice } from "@/app/dashboard/actions";
import type { DeviceRequest } from "@/lib/console/device";

type Project = { id: string; name: string };
type Step = "enter" | "confirm" | "approved" | "denied";

const NEW = "new";

function minutesAgo(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 60_000));
  if (mins < 1) return "less than a minute ago";
  return mins === 1 ? "1 minute ago" : `${mins} minutes ago`;
}

export function DeviceApprove({
  initialCode,
  projects: initialProjects,
  projectsError,
}: {
  initialCode: string;
  projects: Project[];
  projectsError: boolean;
}) {
  const [step, setStep] = useState<Step>("enter");
  const [codeInput, setCodeInput] = useState(initialCode);
  const [code, setCode] = useState("");
  const [device, setDevice] = useState<DeviceRequest | null>(null);
  const [projects, setProjects] = useState<Project[]>(initialProjects);
  const [choice, setChoice] = useState<string>(initialProjects[0]?.id ?? NEW);
  const [newName, setNewName] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function onContinue(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const r = await inspectDevice(codeInput);
      if (!r.ok) {
        setError(r.error);
        return;
      }
      setCode(r.code);
      setDevice(r.device);
      setStep("confirm");
    } catch {
      setError("Could not check the code. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function onApprove() {
    setBusy(true);
    setError("");
    try {
      let projectId = choice;
      if (choice === NEW) {
        const created = await createProject(newName);
        if (!created.ok) {
          setError(created.error);
          return;
        }
        // Remember it, so a retry after a failed approval does not create a second project.
        projectId = created.id;
        setProjects((list) => [...list, { id: created.id, name: newName.trim().replace(/\s+/g, " ") }]);
        setChoice(created.id);
      }
      const r = await approveDevice(code, projectId, confirmed);
      if (!r.ok) {
        setError(r.error);
        return;
      }
      setStep("approved");
    } catch {
      setError("Could not approve the sign-in. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function onDeny() {
    setBusy(true);
    setError("");
    try {
      const r = await denyDevice(code || codeInput);
      if (!r.ok) {
        setError(r.error);
        return;
      }
      setStep("denied");
    } catch {
      setError("Could not deny the request. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  if (step === "approved") {
    return (
      <div role="status" className="rounded border border-line bg-panel p-4">
        <p className="font-medium">Approved.</p>
        <p className="mt-1 text-sm text-dim">Go back to your terminal. It finishes on its own within a few seconds.</p>
      </div>
    );
  }
  if (step === "denied") {
    return (
      <div role="status" className="rounded border border-line bg-panel p-4">
        <p className="font-medium">Request denied.</p>
        <p className="mt-1 text-sm text-dim">Nothing was linked. You can close this tab.</p>
      </div>
    );
  }

  if (step === "enter" || !device) {
    return (
      <form onSubmit={onContinue} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-xs text-dim">
          Code from your terminal
          <input
            name="userCode"
            autoComplete="off"
            autoCapitalize="characters"
            spellCheck={false}
            value={codeInput}
            onChange={(e) => setCodeInput(e.target.value)}
            maxLength={12}
            required
            className="w-48 rounded border border-line bg-panel px-3 py-2 font-mono text-base tracking-widest text-text"
            placeholder="XXXX-XXXX"
          />
        </label>
        <div>
          <button disabled={busy} className="rounded bg-stable px-4 py-2 text-sm font-medium text-bg disabled:opacity-50">
            {busy ? "Checking..." : "Continue"}
          </button>
        </div>
        {error && <p role="alert" className="text-sm text-alert">{error}</p>}
      </form>
    );
  }

  const projectOk = choice === NEW ? newName.trim().length > 0 : projects.some((p) => p.id === choice);

  return (
    <div className="flex flex-col gap-5">
      <section className="rounded border border-line bg-panel p-4" aria-labelledby="device-facts">
        <h2 id="device-facts" className="text-sm font-semibold">Is this you?</h2>
        <p className="mt-2 text-sm">
          A device called <strong>{device.deviceName}</strong> ({device.deviceOs}) asked to sign in{" "}
          {minutesAgo(device.requestedAt)}.
        </p>
        <p className="mt-2 text-xs text-dim">The device chose this name itself, so it does not prove who is behind it.</p>
        <p className="mt-1 text-xs text-dim">If someone else gave you this code, choose Deny.</p>
      </section>

      <fieldset className="flex flex-col gap-2" disabled={busy}>
        <legend className="text-sm font-semibold">Send its drift scores to</legend>
        {projectsError && (
          <p role="alert" className="text-sm text-alert">Could not load your projects. You can still create a new one.</p>
        )}
        <select
          aria-label="Project"
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          className="w-64 rounded border border-line bg-panel px-3 py-2 text-sm text-text"
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
          <option value={NEW}>Create a new project...</option>
        </select>
        {choice === NEW && (
          <input
            aria-label="New project name"
            autoComplete="off"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            maxLength={64}
            className="w-64 rounded border border-line bg-panel px-3 py-2 text-sm text-text"
            placeholder="My LLM app"
          />
        )}
      </fieldset>

      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
          className="mt-1"
        />
        <span>I started this sign-in myself, from the terminal I am using right now.</span>
      </label>

      <div className="flex gap-3">
        <button
          onClick={onApprove}
          disabled={busy || !confirmed || !projectOk}
          className="rounded bg-stable px-4 py-2 text-sm font-medium text-bg disabled:opacity-50"
        >
          {busy ? "Working..." : "Approve"}
        </button>
        <button
          onClick={onDeny}
          disabled={busy}
          className="rounded border border-line px-4 py-2 text-sm disabled:opacity-50"
        >
          Deny
        </button>
      </div>
      {error && <p role="alert" className="text-sm text-alert">{error}</p>}
    </div>
  );
}
