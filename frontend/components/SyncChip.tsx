// React import: tsx test runner uses the classic JSX transform.
import React from "react";

export type SyncState = "live" | "connecting" | "offline" | "synced" | "pending" | "paused";

const STYLE: Record<SyncState, { dot: string; text: string }> = {
  live: { dot: "bg-stable", text: "Live" },
  connecting: { dot: "bg-drift", text: "Connecting" },
  offline: { dot: "bg-alert", text: "Offline" },
  synced: { dot: "bg-stable", text: "Synced" },
  pending: { dot: "bg-drift", text: "pending" },
  paused: { dot: "bg-dim", text: "Paused" },
};

// Shared by the cloud console (live / connecting / offline) and, later, the
// local dashboard (synced / pending / paused).
export function SyncChip({ state, detail }: { state: SyncState; detail?: string }) {
  const s = STYLE[state];
  return (
    <span
      role="status"
      className="inline-flex items-center gap-1.5 rounded border border-line px-2 py-1 text-xs text-dim"
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
      {state === "pending" && detail ? `${detail} ${s.text}` : s.text}
    </span>
  );
}
