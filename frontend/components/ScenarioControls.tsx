"use client";

import { useState } from "react";
import { MonitorRequestError, MonitorUnreachableError } from "@/lib/api";
import type { ScenarioName } from "@/lib/types";

interface ScenarioControlsProps {
  active: Record<ScenarioName, boolean>;
  // Always activates, even when already active - injection-creep escalates
  // one step per call (up to 3, see demo_bot/scenarios.py's
  // INJECTION_FRAGMENTS) and a click that toggled it off after one step
  // would make steps 2-3 unreachable from the UI. "Reset to stable" is the
  // only way to turn a scenario back off, matching the backend's own
  // activate/reset action pair.
  onActivate: (name: ScenarioName) => Promise<void>;
  onResetAll: () => Promise<void>;
  disabled: boolean;
}

const SCENARIOS: { name: ScenarioName; label: string; hint: string; mark: string }[] = [
  {
    name: "model-downgrade",
    label: "Simulate model downgrade",
    hint: "swaps the bot to a weaker model — watch canary accuracy",
    mark: "▽",
  },
  {
    name: "injection-creep",
    label: "Simulate prompt injection creep",
    hint: "corrupts the system prompt over several calls — watch hallucination score",
    mark: "≈",
  },
  {
    name: "distribution-shift",
    label: "Simulate distribution shift",
    hint: "floods off-topic queries — watch embedding drift",
    mark: "↯",
  },
];

function describeError(err: unknown): string {
  if (err instanceof MonitorRequestError) return `Couldn't do that: ${err.message}`;
  if (err instanceof MonitorUnreachableError) return "Monitor is unreachable right now.";
  return "Something went wrong.";
}

export function ScenarioControls({ active, onActivate, onResetAll, disabled }: ScenarioControlsProps) {
  const [pending, setPending] = useState<ScenarioName | "reset" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const anyActive = Object.values(active).some(Boolean);

  async function handleActivate(name: ScenarioName) {
    setPending(name);
    setError(null);
    try {
      await onActivate(name);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPending(null);
    }
  }

  async function handleReset() {
    setPending("reset");
    setError(null);
    try {
      await onResetAll();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {SCENARIOS.map((s) => {
        const isActive = active[s.name];
        return (
          <button
            key={s.name}
            onClick={() => handleActivate(s.name)}
            disabled={disabled || pending !== null}
            aria-pressed={isActive}
            className={`group flex items-start gap-3 rounded border px-4 py-3 text-left text-sm transition-all disabled:opacity-40 ${
              isActive
                ? "border-drift bg-drift/10 text-drift"
                : "border-line bg-panel text-text hover:-translate-y-px hover:border-dim hover:shadow-[0_2px_0_0_rgba(30,39,51,0.6)]"
            }`}
          >
            <span
              className={`mt-0.5 font-mono text-xs ${isActive ? "text-drift" : "text-dim group-hover:text-text"}`}
            >
              {s.mark}
            </span>
            <span className="flex-1">
              <span className="block font-medium">{s.label}</span>
              <span className="mt-0.5 block text-xs text-dim">{s.hint}</span>
            </span>
            {pending === s.name && <span className="mt-0.5 text-xs text-dim">…</span>}
          </button>
        );
      })}
      <button
        onClick={handleReset}
        disabled={disabled || pending !== null || !anyActive}
        className="mt-1 rounded border border-line px-4 py-2 text-sm text-dim transition-colors hover:border-stable hover:text-stable disabled:opacity-40"
      >
        Reset to stable
      </button>
      {error && <p className="text-xs text-alert">{error}</p>}
    </div>
  );
}
