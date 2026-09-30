"use client";

import type { QuotaState } from "@/lib/types";

export function QuotaBadge({ quota }: { quota: QuotaState | null }) {
  if (!quota) {
    return <span className="text-xs text-dim">quota —</span>;
  }
  const pct = quota.limit > 0 ? quota.used / quota.limit : 0;
  const color = quota.exceeded ? "text-alert" : pct > 0.8 ? "text-drift" : "text-dim";
  return (
    <div className="flex items-center gap-2">
      <span className={`font-mono text-xs tabular ${color}`}>
        API calls: {quota.used}/{quota.limit} used today
      </span>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
        <div
          className={`h-full ${quota.exceeded ? "bg-alert" : "bg-stable"}`}
          style={{ width: `${Math.min(100, pct * 100)}%` }}
        />
      </div>
    </div>
  );
}
