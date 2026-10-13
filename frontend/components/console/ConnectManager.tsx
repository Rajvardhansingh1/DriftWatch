"use client";

// React import: the tsx test runner uses the classic JSX transform.
import React, { useState } from "react";
import { connectModel, removeConnection, saveConnection, saveProbes } from "@/app/dashboard/connect-actions";
import { estimateUsage, STARTER_PROBES, type ProbeInput, type RunStatus } from "@/lib/connect/core";

export type ConnectedModel = {
  provider: string;
  model: string;
  last4: string;
  interval_minutes: number;
  monthly_budget: number;
  enabled: boolean;
  calls_this_month: number;
  last_run_at: string | null;
  last_error: string | null;
};

const STATUS_TEXT: Record<RunStatus, string> = {
  waiting: "Waiting for the first run.",
  ok: "Running normally.",
  late: "The last run is late. The scheduled runner may be paused; the owner has been alerted.",
  error: "The last run failed.",
  paused: "Paused.",
};

const input = "mt-1 w-full rounded border border-line bg-panel px-3 py-2 text-sm";
const button = "rounded border border-line px-3 py-1.5 text-sm hover:border-dim disabled:opacity-50";

export function ConnectManager(props: {
  projectId: string;
  model: ConnectedModel | null;
  probes: ProbeInput[];
  status: RunStatus;
  canEdit: boolean;
}) {
  const { projectId, model, canEdit } = props;
  const [provider, setProvider] = useState("groq");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [interval, setIntervalMinutes] = useState(model?.interval_minutes ?? 60);
  const [budget, setBudget] = useState(model?.monthly_budget ?? 2000);
  const [probes, setProbes] = useState<ProbeInput[]>(props.probes.length ? props.probes : STARTER_PROBES);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const usage = estimateUsage({ probes: probes.length, intervalMinutes: interval, monthlyBudget: budget });

  async function run(task: () => Promise<{ ok: boolean; error?: string }>, done: string) {
    setBusy(true);
    setMessage(null);
    const r = await task();
    setBusy(false);
    setMessage(r.ok ? done : (r.error ?? "Something went wrong."));
    return r.ok;
  }

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    const key = apiKey;
    setApiKey(""); // the key leaves the page state the moment it is submitted
    await run(() => connectModel(projectId, { provider, model: modelName, apiKey: key, intervalMinutes: interval, monthlyBudget: budget }), "Connected. The first run happens within about 15 minutes.");
  }

  return (
    <div className="space-y-8">
      <section className="rounded border border-line bg-panel p-4 text-sm" aria-label="What this does">
        <p>
          DriftWatch will ask your model a few fixed questions on a schedule and track whether its answers change. This measures
          the <strong>model with fixed questions</strong>, not your app&apos;s real traffic. For real traffic, use the local agent.
        </p>
        <p className="mt-2 text-dim">
          <strong>This uses your provider account.</strong> Every question is a call you pay your provider for. Your key reaches our server over an
          encrypted connection, is checked once with your provider, and is then sealed with a key that only the scheduled runner holds before it
          is stored. After that the website and the database cannot read it. You can delete it here at any time.
        </p>
      </section>

      {model && (
        <section aria-label="Connected model" className="rounded border border-line bg-panel p-4 text-sm">
          <h2 className="font-medium">Connected</h2>
          <p className="mt-2">
            {model.provider} / {model.model}, key ending in <span className="font-mono">{model.last4}</span>
          </p>
          <p className="mt-1 text-dim">
            {STATUS_TEXT[props.status]} {model.last_run_at ? `Last run ${new Date(model.last_run_at).toISOString().slice(0, 16).replace("T", " ")} UTC.` : ""}
          </p>
          {model.last_error && <p className="mt-1 text-alert">{model.last_error}</p>}
          <p className="mt-1 text-dim">{model.calls_this_month} of {model.monthly_budget} calls used this month.</p>
        </section>
      )}

      {canEdit && (
        <form onSubmit={connect} className="space-y-3" aria-label={model ? "Replace the key" : "Connect a model"}>
          <h2 className="font-medium">{model ? "Replace the model or key" : "Connect a model"}</h2>
          <label className="block text-sm">
            Provider
            <select className={input} value={provider} onChange={(e) => setProvider(e.target.value)}>
              <option value="groq">Groq</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>
          <label className="block text-sm">
            Model name
            <input className={input} value={modelName} onChange={(e) => setModelName(e.target.value)} placeholder="the exact model name" required maxLength={80} />
          </label>
          <label className="block text-sm">
            API key
            <input
              className={input}
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              required
              maxLength={512}
            />
          </label>
          <button className={button} disabled={busy}>
            {busy ? "Checking the key..." : model ? "Replace" : "Connect"}
          </button>
        </form>
      )}

      {canEdit && model && (
        <section aria-label="Schedule and budget" className="space-y-3">
          <h2 className="font-medium">Schedule and budget</h2>
          <div className="flex flex-wrap gap-4">
            <label className="text-sm">
              Run every (minutes, 15 to 1440)
              <input className={input} type="number" min={15} max={1440} value={interval} onChange={(e) => setIntervalMinutes(Number(e.target.value))} />
            </label>
            <label className="text-sm">
              Monthly call budget
              <input className={input} type="number" min={1} max={100000} value={budget} onChange={(e) => setBudget(Number(e.target.value))} />
            </label>
          </div>
          <p className="text-xs text-dim" aria-label="Usage estimate">
            About {usage.callsPerRun} calls a run, up to {usage.callsPerMonth} calls a month, at most about {usage.tokensCeiling.toLocaleString("en-US")} tokens.
            Check your provider&apos;s price for that model: DriftWatch does not know it. The runner stops when the budget is used.
          </p>
          <div className="flex gap-2">
            <button className={button} disabled={busy} onClick={() => run(() => saveConnection(projectId, { intervalMinutes: interval, monthlyBudget: budget, enabled: true }), "Saved.")}>
              Save
            </button>
            <button className={button} disabled={busy} onClick={() => run(() => saveConnection(projectId, { intervalMinutes: interval, monthlyBudget: budget, enabled: !model.enabled }), model.enabled ? "Paused." : "Resumed.")}>
              {model.enabled ? "Pause" : "Resume"}
            </button>
          </div>
        </section>
      )}

      {canEdit && model && (
        <section aria-label="Probes" className="space-y-3">
          <h2 className="font-medium">Probe questions</h2>
          <p className="text-xs text-dim">Up to five. A probe passes when the answer contains (or exactly equals) the expected text. Changing them restarts the baseline.</p>
          {probes.map((p, i) => (
            <div key={i} className="rounded border border-line p-3">
              <label className="block text-sm">
                Question
                <textarea className={input} rows={2} maxLength={500} value={p.prompt} onChange={(e) => setProbes(probes.map((q, j) => (j === i ? { ...q, prompt: e.target.value } : q)))} />
              </label>
              <div className="mt-2 flex flex-wrap gap-3">
                <label className="text-sm">
                  Expected answer
                  <input className={input} maxLength={200} value={p.expected} onChange={(e) => setProbes(probes.map((q, j) => (j === i ? { ...q, expected: e.target.value } : q)))} />
                </label>
                <label className="text-sm">
                  Match
                  <select className={input} value={p.match_type} onChange={(e) => setProbes(probes.map((q, j) => (j === i ? { ...q, match_type: e.target.value as ProbeInput["match_type"] } : q)))}>
                    <option value="contains">contains</option>
                    <option value="exact">exactly</option>
                  </select>
                </label>
              </div>
            </div>
          ))}
          <div className="flex gap-2">
            {probes.length < 5 && (
              <button className={button} type="button" onClick={() => setProbes([...probes, { prompt: "", expected: "", match_type: "contains" }])}>
                Add a probe
              </button>
            )}
            {probes.length > 1 && (
              <button className={button} type="button" onClick={() => setProbes(probes.slice(0, -1))}>
                Remove the last
              </button>
            )}
            <button className={button} disabled={busy} onClick={() => run(() => saveProbes(projectId, probes), "Probes saved.")}>
              Save probes
            </button>
          </div>
        </section>
      )}

      {canEdit && model && (
        <section aria-label="Delete" className="rounded border border-line p-4 text-sm">
          <h2 className="font-medium">Delete the connection</h2>
          <p className="mt-1 text-dim">Removes the encrypted key, the schedule and the stored reference numbers for this project. Past scores stay.</p>
          <button className={`${button} mt-3`} disabled={busy} onClick={() => confirm("Delete the connected model and its key?") && run(() => removeConnection(projectId), "Deleted.")}>
            Delete key and connection
          </button>
        </section>
      )}

      {!canEdit && <p className="text-sm text-dim">Only project admins can change this.</p>}
      {message && <p role="status" className="text-sm">{message}</p>}
    </div>
  );
}
