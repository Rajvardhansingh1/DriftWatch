"use client";

interface AlertBannerProps {
  alert: boolean;
  triggeringSignals: string[];
}

const SIGNAL_LABELS: Record<string, string> = {
  embedding_drift: "embedding drift",
  self_consistency: "self-consistency",
  canary_accuracy: "canary accuracy",
  judge_trend: "judge trend",
  hallucination_score: "hallucination score",
};

export function AlertBanner({ alert, triggeringSignals }: AlertBannerProps) {
  return (
    <div
      aria-hidden={!alert}
      className={`overflow-hidden transition-[max-height,opacity] duration-300 ease-out ${
        alert ? "max-h-20 opacity-100" : "max-h-0 opacity-0"
      }`}
    >
      <div className="flex items-center gap-3 border-b border-alert/40 bg-alert/10 px-6 py-3">
        <span className="h-2 w-2 shrink-0 rounded-full bg-alert" />
        <p className="text-sm text-text">
          Combined drift score crossed threshold —{" "}
          <span className="font-mono text-alert">
            {triggeringSignals.map((s) => SIGNAL_LABELS[s] ?? s).join(", ") || "no signal detail"}
          </span>
        </p>
      </div>
    </div>
  );
}
