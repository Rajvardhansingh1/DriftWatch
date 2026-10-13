// React import: the tsx test runner uses the classic JSX transform.
import React from "react";
import { quotaLine, type Quota } from "@/lib/console/quota";

// Server-rendered: numbers only, no client code. Shown when the free allowance is a live feature.
export function AllowanceNote({ quota }: { quota: Quota }) {
  const used = Math.min(quota.used, quota.cap);
  const spent = quota.cap > 0 && used >= quota.cap;
  return (
    <section aria-label="Free allowance" className="mt-4 rounded border border-line bg-panel p-4 text-sm">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="font-medium">Free allowance</h2>
        <span className="font-mono text-xs text-dim tabular">{quotaLine(quota)}</span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={quota.cap}
        aria-valuenow={used}
        className="mt-3 h-1.5 w-full overflow-hidden rounded bg-line"
      >
        <div className={`h-full ${spent ? "bg-alert" : "bg-stable"}`} style={{ width: `${quota.cap ? (used / quota.cap) * 100 : 0}%` }} />
      </div>
      <p className="mt-3 text-xs text-dim">
        Grading a small sample of your app&apos;s responses with <code>driftwatch judge enable</code> uses it. The text is
        redacted on your machine first, and the relay keeps nothing.
        {spent && (
          <>
            {" "}
            To keep going on your own account: <code>driftwatch key set groq</code>, then <code>driftwatch judge enable --own</code>.
          </>
        )}
      </p>
    </section>
  );
}
