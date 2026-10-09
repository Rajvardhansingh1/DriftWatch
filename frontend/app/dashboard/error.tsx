"use client";

export default function DashboardError({ reset }: { error: Error; reset: () => void }) {
  return (
    <main role="alert">
      <p className="text-sm text-alert">Something went wrong loading your projects.</p>
      <button onClick={reset} className="mt-3 rounded border border-line bg-panel px-3 py-1.5 text-sm text-text hover:border-dim">
        Try again
      </button>
    </main>
  );
}
