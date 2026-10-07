"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getScore } from "@/lib/api";
import { Skeleton } from "./Skeleton";

type State = { kind: "loading" } | { kind: "ok"; score: number; alert: boolean } | { kind: "asleep" };

export function LiveDemoTeaser() {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let done = false;
    let cancelled = false;
    const timer = setTimeout(() => { if (!done && !cancelled) setState({ kind: "asleep" }); }, 8000);
    getScore()
      .then((s) => { done = true; if (!cancelled) setState({ kind: "ok", score: s.score, alert: s.alert }); })
      .catch(() => { done = true; if (!cancelled) setState({ kind: "asleep" }); })
      .finally(() => clearTimeout(timer));
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  return (
    <div className="mk-tilt rounded-lg border border-[var(--mk-line)] bg-[var(--mk-surface)] p-6">
      <p className="text-sm text-[var(--mk-muted)]">Live demo, combined drift score right now</p>
      <div className="mt-3 min-h-12" aria-live="polite">
        {state.kind === "loading" && <Skeleton label="Loading live demo score" className="h-10 w-40" announce={false} />}
        {state.kind === "ok" && (
          <p className="font-[var(--font-plex-mono)] text-4xl">
            {state.score.toFixed(2)}
            <span className={`ml-3 text-sm ${state.alert ? "text-[var(--mk-warn)]" : "text-[var(--mk-muted)]"}`}>
              {state.alert ? "drift flagged" : "within range"}
            </span>
          </p>
        )}
        {state.kind === "asleep" && (
          <p className="text-sm text-[var(--mk-muted)]">The demo server is asleep. It wakes in about half a minute when you open it.</p>
        )}
      </div>
      <Link href="/demo" className="mt-4 inline-block text-sm text-[var(--mk-accent)] underline">Open the live demo</Link>
    </div>
  );
}
