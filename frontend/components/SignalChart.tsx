"use client";

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  YAxis,
} from "recharts";
import type { SignalPoint } from "@/lib/types";

interface SignalChartProps {
  title: string;
  data: SignalPoint[];
  color: string;
  /** True for signals where a higher raw value means better quality
   * (canary_accuracy, judge_trend) - see combined_score.py's
   * _HIGHER_IS_BETTER. Everywhere else, higher always means more drift. */
  higherIsBetter?: boolean;
}

function Delta({ data, higherIsBetter }: { data: SignalPoint[]; higherIsBetter: boolean }) {
  if (data.length < 2) return null;
  const diff = data[data.length - 1].value - data[data.length - 2].value;
  if (Math.abs(diff) < 0.001) return <span className="text-dim">·</span>;
  const up = diff > 0;
  const isWorse = higherIsBetter ? !up : up;
  return (
    <span className={isWorse ? "text-drift" : "text-stable"}>
      {up ? "▲" : "▼"} {Math.abs(diff).toFixed(3)}
    </span>
  );
}

export function SignalChart({ title, data, color, higherIsBetter = false }: SignalChartProps) {
  const latest = data.length > 0 ? data[data.length - 1].value : null;
  return (
    <div className="rounded border border-l-2 border-line bg-panel p-4" style={{ borderLeftColor: color }}>
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs text-dim">{title}</p>
        <div className="flex items-baseline gap-2 font-mono text-xs tabular">
          <Delta data={data} higherIsBetter={higherIsBetter} />
          <span className="text-sm text-text">{latest === null ? "—" : latest.toFixed(3)}</span>
        </div>
      </div>
      <div className="mt-2 h-20">
        {data.length === 0 ? (
          <div className="flex h-full items-center justify-center text-xs text-dim">
            no data yet
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="#1E2733" strokeDasharray="2 4" vertical={false} />
              <YAxis
                domain={[0, 1]}
                ticks={[0, 0.5, 1]}
                tick={{ fill: "#8A97A6", fontSize: 10, fontFamily: "var(--font-plex-mono)" }}
                axisLine={false}
                tickLine={false}
                width={44}
              />
              <ReferenceLine y={0.5} stroke="#1E2733" strokeDasharray="3 3" />
              <Tooltip
                contentStyle={{
                  background: "#10151D",
                  border: "1px solid #1E2733",
                  borderRadius: 4,
                  fontSize: 12,
                }}
                labelFormatter={() => ""}
                formatter={(value: number) => value.toFixed(3)}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={color}
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
