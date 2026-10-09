import type { SignalSeries } from "@/lib/types";

// higherIsBetter mirrors monitor/scoring/combined_score.py's _HIGHER_IS_BETTER:
// canary_accuracy/judge_trend are quality scores (higher = better), every other
// signal is a drift magnitude (higher = worse).
export type Panel = {
  key: keyof SignalSeries;
  title: string;
  color: string;
  higherIsBetter?: boolean;
};

export const SIGNAL_PANELS: Panel[] = [
  { key: "embedding_drift", title: "embedding drift", color: "#3DDC97" },
  { key: "self_consistency", title: "self-consistency disagreement", color: "#3DDC97" },
  { key: "canary_accuracy", title: "canary accuracy", color: "#F2B84B", higherIsBetter: true },
  { key: "judge_trend", title: "judge trend", color: "#F2B84B", higherIsBetter: true },
  { key: "hallucination_score", title: "hallucination score", color: "#FF5C5C" },
];

export const COMBINED_PANEL: Panel = { key: "combined_score", title: "combined drift score", color: "#E6EDF3" };
