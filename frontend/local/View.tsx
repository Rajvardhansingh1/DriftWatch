import React from "react";
import { SignalChart } from "@/components/SignalChart";
import { SyncChip } from "@/components/SyncChip";
import { COMBINED_PANEL, SIGNAL_PANELS } from "@/lib/panels";
import type { SignalSeries } from "@/lib/types";
import { RANGES, syncChip, type LocalRange } from "./api";

export type ViewProps = {
  projects: string[];
  project: string | null;
  range: LocalRange;
  series: SignalSeries;
  status: Parameters<typeof syncChip>[0];
  embedder?: string;
  signedIn: boolean;
  error: string | null;
  onProject?: (id: string) => void;
  onRange?: (r: LocalRange) => void;
};

export function View(p: ViewProps) {
  if (!p.signedIn) {
    return (
      <main className="mx-auto max-w-2xl p-6">
        <h1 className="text-xl font-semibold">DriftWatch, on this machine</h1>
        <p className="mt-4 rounded border border-line bg-panel p-4 text-sm text-dim">
          {p.error ?? "Open this page with `driftwatch dashboard` in your terminal. It signs you in with a one-time link."}
        </p>
      </main>
    );
  }
  // Only the signals this agent can measure on its own are shown; the rest appear if values ever arrive.
  const panels = [COMBINED_PANEL, ...SIGNAL_PANELS].filter(
    (panel) => panel.key === "combined_score" || panel.key === "embedding_drift" || p.series[panel.key].length > 0,
  );
  const empty = Object.values(p.series).every((points) => points.length === 0);
  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold">DriftWatch, on this machine</h1>
        <SyncChip {...syncChip(p.status)} />
      </div>
      <p className="mt-2 text-xs text-dim">
        Computed here from the numbers your agent holds. Response text is never stored, so none can be shown. Nothing on
        this page leaves your machine.
      </p>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
        {p.projects.length > 1 ? (
          <select
            aria-label="Project"
            className="rounded border border-line bg-panel px-2 py-1"
            value={p.project ?? ""}
            onChange={(e) => p.onProject?.(e.target.value)}
          >
            {p.projects.map((id) => (
              <option key={id} value={id}>
                {id}
              </option>
            ))}
          </select>
        ) : (
          <span className="font-mono text-xs text-dim">{p.project ?? "no project yet"}</span>
        )}
        <nav aria-label="Range" className="flex gap-2">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              aria-current={r === p.range ? "page" : undefined}
              className={r === p.range ? "text-text underline" : "text-dim hover:text-text"}
              onClick={() => p.onRange?.(r)}
            >
              {r}
            </button>
          ))}
        </nav>
      </div>
      {p.embedder && p.embedder !== "ready" && (
        <p className="mt-4 rounded border border-line bg-panel p-3 text-sm text-dim">
          The model is {p.embedder}. Numbers appear once it has loaded and a baseline is collected.
        </p>
      )}
      {empty && (
        <p className="mt-4 rounded border border-line bg-panel p-4 text-sm text-dim">
          No drift values in this range yet. The baseline needs about 200 responses (30 at the least); then a value appears
          about once a minute while your app runs.
        </p>
      )}
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {panels.map((panel) => (
          <SignalChart key={panel.key} title={panel.title} data={p.series[panel.key]} color={panel.color} higherIsBetter={panel.higherIsBetter} />
        ))}
      </div>
    </main>
  );
}
