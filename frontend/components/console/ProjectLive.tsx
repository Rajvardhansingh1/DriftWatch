"use client";

import { useEffect, useState } from "react";
import { SignalChart } from "@/components/SignalChart";
import { SyncChip } from "@/components/SyncChip";
import { COMBINED_PANEL, SIGNAL_PANELS } from "@/lib/panels";
import { appendPoint, MAX_POINTS } from "@/lib/console/series";
import { subscribeToProject, type ClientLike, type LiveStatus } from "@/lib/console/realtime";
import { isLiveRange, type Range } from "@/lib/console/validate";
import { getSupabaseClient } from "@/lib/supabase";
import type { SignalSeries } from "@/lib/types";

export function ProjectLive({ projectId, range, initial }: { projectId: string; range: Range; initial: SignalSeries }) {
  const [series, setSeries] = useState<SignalSeries>(initial);
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const live = isLiveRange(range);

  useEffect(() => {
    setSeries(initial);
  }, [initial]);

  useEffect(() => {
    if (!live) return;
    setStatus("connecting");
    const client = getSupabaseClient();
    if (!client) {
      setStatus("offline");
      return;
    }
    const unsubscribe = subscribeToProject(
      client as unknown as ClientLike,
      projectId,
      (row) => setSeries((prev) => appendPoint(prev, row)),
      setStatus,
    );
    return () => unsubscribe();
  }, [projectId, live]);

  const empty = Object.values(series).every((points) => points.length === 0);
  return (
    <section aria-label="Signals">
      <div className="mb-4 flex items-center justify-between gap-3">
        <p className="text-xs text-dim">{live ? "Updates as events arrive." : "Hourly averages; not live."}</p>
        <SyncChip state={live ? status : "paused"} />
      </div>
      {Object.values(series).some((points) => points.length >= MAX_POINTS) && (
        <p className="mb-4 text-xs text-dim">Showing the latest {MAX_POINTS} points per chart.</p>
      )}
      {empty && (
        <p className="mb-4 rounded border border-line bg-panel p-4 text-sm text-dim">
          No signals in this range yet. Make an API key for this project and send an event.
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {[COMBINED_PANEL, ...SIGNAL_PANELS].map((p) => (
          <SignalChart key={p.key} title={p.title} data={series[p.key]} color={p.color} higherIsBetter={p.higherIsBetter} />
        ))}
      </div>
    </section>
  );
}
