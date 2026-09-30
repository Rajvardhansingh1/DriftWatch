"use client";

export function ColdStartOverlay({ visible }: { visible: boolean }) {
  if (!visible) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-bg/95">
      <div className="text-center">
        <div className="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-line border-t-drift" />
        <p className="mt-4 font-mono text-sm text-dim">waking the monitor, ~20-30s</p>
        <p className="mt-1 text-xs text-dim">free-tier hosting sleeps after 15 minutes idle</p>
      </div>
    </div>
  );
}
