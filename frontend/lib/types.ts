export type SignalName =
  | "embedding_drift"
  | "self_consistency"
  | "canary_accuracy"
  | "judge_trend"
  | "hallucination_score"
  | "combined_score";

export interface SignalPoint {
  timestamp: string;
  value: number;
}

export type SignalSeries = Record<SignalName, SignalPoint[]>;

export interface QuotaState {
  used: number;
  limit: number;
  remaining: number;
  exceeded: boolean;
}

export interface QueryResponse {
  query: string | null;
  response: string | null;
  model_id: string;
  score: number;
  alert: boolean;
  triggering_signals: string[];
  cached: boolean;
}

export interface ScenarioState {
  model_downgraded: boolean;
  injection_active: boolean;
  distribution_shift_active: boolean;
}

export interface ScoreState {
  score: number;
  alert: boolean;
  triggering_signals: string[];
  contributions: Record<string, number>;
  scenario: ScenarioState;
}

export type ScenarioName = "model-downgrade" | "injection-creep" | "distribution-shift";

export interface ScenarioActivationResult {
  model_id: string;
  prompt_version: number;
  distribution_shift_active: boolean;
}
