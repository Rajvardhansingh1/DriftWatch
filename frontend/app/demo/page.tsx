"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getHealth,
  getQuota,
  getScore,
  getSignals,
  postQuery,
  postScenario,
  resetAllScenarios,
} from "@/lib/api";
import { AlertBanner } from "@/components/AlertBanner";
import { ColdStartOverlay } from "@/components/ColdStartOverlay";
import { CombinedScoreReadout } from "@/components/CombinedScoreReadout";
import { FreeTextQuery } from "@/components/FreeTextQuery";
import { QuotaBadge } from "@/components/QuotaBadge";
import { ScenarioControls } from "@/components/ScenarioControls";
import { SignalChart } from "@/components/SignalChart";
import type {
  QuotaState,
  ScenarioName,
  ScenarioState,
  ScoreState,
  SignalSeries,
} from "@/lib/types";

// The backend's SharedRateLimiter allows 25 calls/60s (monitor/main.py),
// calibrated to Groq's real free-tier ceiling. One auto-query cycle
// averages 1 primary + 3 self-consistency samples + 0.25 judge (every
// 4th cycle) = 4.25 calls, so this loop alone must stay under ~5.9
// cycles/min (25 / 4.25) to avoid eating the whole budget by itself -
// 15s (4 cycles/min, 17 calls/min) leaves headroom for manual free-text
// queries and scenario-triggered canary refreshes on the same budget.
// The backend degrades gracefully either way (serves the last cached
// result, never errors) - this interval just keeps that the exception
// rather than the common case.
const AUTO_QUERY_INTERVAL_MS = 15000;
const POLL_INTERVAL_MS = 3000;

const EMPTY_SCENARIO_STATE: ScenarioState = {
  model_downgraded: false,
  injection_active: false,
  distribution_shift_active: false,
};

// higherIsBetter mirrors monitor/scoring/combined_score.py's
// _HIGHER_IS_BETTER - canary_accuracy/judge_trend are quality scores
// (higher = better), every other signal is a drift magnitude (higher = worse).
const SIGNAL_PANELS: {
  key: keyof SignalSeries;
  title: string;
  color: string;
  higherIsBetter?: boolean;
}[] = [
  { key: "embedding_drift", title: "embedding drift", color: "#3DDC97" },
  { key: "self_consistency", title: "self-consistency disagreement", color: "#3DDC97" },
  { key: "canary_accuracy", title: "canary accuracy", color: "#F2B84B", higherIsBetter: true },
  { key: "judge_trend", title: "judge trend", color: "#F2B84B", higherIsBetter: true },
  { key: "hallucination_score", title: "hallucination score", color: "#FF5C5C" },
];

export default function DashboardPage() {
  const [awake, setAwake] = useState(false);
  const [signals, setSignals] = useState<SignalSeries | null>(null);
  const [quota, setQuota] = useState<QuotaState | null>(null);
  const [score, setScore] = useState<ScoreState | null>(null);
  const [scenarioState, setScenarioState] = useState<ScenarioState>(EMPTY_SCENARIO_STATE);
  const [lastResponse, setLastResponse] = useState<string | null>(null);
  const autoQueryEnabled = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const [sig, q, sc] = await Promise.all([getSignals(50), getQuota(), getScore()]);
      setSignals(sig);
      setQuota(q);
      setScore(sc);
      setScenarioState(sc.scenario);
    } catch {
      // transient — next poll tick will retry
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function waitForServer() {
      while (!cancelled) {
        try {
          await getHealth();
          if (!cancelled) setAwake(true);
          return;
        } catch {
          await new Promise((r) => setTimeout(r, 2000));
        }
      }
    }
    waitForServer();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!awake) return;
    refresh();
    const pollId = setInterval(refresh, POLL_INTERVAL_MS);
    const autoQueryId = setInterval(async () => {
      if (!autoQueryEnabled.current) return;
      try {
        await postQuery();
      } catch {
        // ignore — quota exhaustion / transient error, next tick retries
      }
    }, AUTO_QUERY_INTERVAL_MS);
    return () => {
      clearInterval(pollId);
      clearInterval(autoQueryId);
    };
  }, [awake, refresh]);

  async function handleScenarioActivate(name: ScenarioName) {
    await postScenario(name, "activate");
    await refresh();
  }

  async function handleResetAll() {
    await resetAllScenarios();
    await refresh();
  }

  async function handleFreeTextQuery(text: string) {
    const result = await postQuery(text);
    setLastResponse(result.response);
    await refresh();
  }

  const combinedHistory = signals?.combined_score ?? [];
  const latestScore = score?.score ?? 0;
  const latestAlert = score?.alert ?? false;
  const triggeringSignals = score?.triggering_signals ?? [];
  const activeByName: Record<ScenarioName, boolean> = {
    "model-downgrade": scenarioState.model_downgraded,
    "injection-creep": scenarioState.injection_active,
    "distribution-shift": scenarioState.distribution_shift_active,
  };

  return (
    <main className="min-h-screen">
      <ColdStartOverlay visible={!awake} />
      <p className="border-b border-line bg-black/20 px-6 py-1.5 text-center text-xs text-dim">
        Demo: this dashboard is shared by every visitor, so scenarios you trigger are visible to others.
      </p>
      <header className="flex items-center justify-between border-b border-line px-6 py-4">
        <div className="flex items-center gap-3">
          <span className="flex h-7 w-7 items-center justify-center rounded border border-line font-mono text-xs text-dim">
            DW
          </span>
          <div>
            <h1 className="text-lg font-medium text-text">DriftWatch</h1>
            <p className="text-xs text-dim">
              Silent quality drift, made visible. Detects drift — not always why.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <QuotaBadge quota={quota} />
          <span className="flex items-center gap-1.5 text-xs text-dim">
            <span className="relative flex h-1.5 w-1.5">
              <span
                className={`pulse-dot relative inline-flex h-1.5 w-1.5 rounded-full ${awake ? "bg-stable text-stable" : "bg-dim text-dim"}`}
              />
            </span>
            {awake ? "live" : "waking"}
          </span>
        </div>
      </header>

      <AlertBanner alert={latestAlert} triggeringSignals={triggeringSignals} />

      <div className="grid grid-cols-1 gap-4 p-6 lg:grid-cols-[280px_1fr]">
        <aside className="flex flex-col gap-4">
          <CombinedScoreReadout score={latestScore} alert={latestAlert} history={combinedHistory} />
          <div>
            <p className="mb-2 text-xs text-dim">scenarios</p>
            <ScenarioControls
              active={activeByName}
              onActivate={handleScenarioActivate}
              onResetAll={handleResetAll}
              disabled={!awake}
            />
          </div>
          <FreeTextQuery onSubmit={handleFreeTextQuery} disabled={!awake} lastResponse={lastResponse} />
        </aside>

        <section className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          {SIGNAL_PANELS.map((p) => (
            <SignalChart
              key={p.key}
              title={p.title}
              data={signals?.[p.key] ?? []}
              color={p.color}
              higherIsBetter={p.higherIsBetter}
            />
          ))}
        </section>
      </div>
    </main>
  );
}
