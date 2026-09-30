"use client";

import { Line, LineChart, ResponsiveContainer, YAxis } from "recharts";
import type { SignalPoint } from "@/lib/types";

interface CombinedScoreReadoutProps {
  score: number;
  alert: boolean;
  history: SignalPoint[];
}

export function CombinedScoreReadout({ score, alert, history }: CombinedScoreReadoutProps) {
  // Two states, not a guessed middle "warning" cutoff: the backend owns
  // the actual threshold (monitor/config.py) and doesn't expose it, so
  // any fixed number here would drift out of sync with it, the way an
  // earlier 0.35 cutoff silently went stale after the threshold was
  // retuned to 0.17.
  const color = alert ? "#FF5C5C" : "#3DDC97";
  return (
    <div className="rounded border border-l-2 border-line bg-panel p-5" style={{ borderLeftColor: color }}>
      <p className="text-xs text-dim">combined drift score</p>
      <p className="mt-1 font-mono text-5xl tabular" style={{ color }}>
        {score.toFixed(2)}
      </p>
      <p className="mt-1 text-xs text-dim">
        {alert ? "threshold crossed" : "within stable range"}
      </p>
      <div className="mt-4 h-16">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={history}>
            <YAxis domain={[0, 1]} hide />
            <Line
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
