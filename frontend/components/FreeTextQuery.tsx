"use client";

import { useState } from "react";
import { MonitorRequestError, MonitorUnreachableError } from "@/lib/api";

const MAX_LENGTH = 500;

interface FreeTextQueryProps {
  onSubmit: (text: string) => Promise<void>;
  disabled: boolean;
  lastResponse: string | null;
}

export function FreeTextQuery({ onSubmit, disabled, lastResponse }: FreeTextQueryProps) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setPending(true);
    setError(null);
    try {
      await onSubmit(text.trim());
      setText("");
    } catch (err) {
      if (err instanceof MonitorRequestError) {
        setError(`Couldn't send that: ${err.message}`);
      } else if (err instanceof MonitorUnreachableError) {
        setError("Monitor is unreachable right now. Try again in a moment.");
      } else {
        setError("Something went wrong sending that.");
      }
    } finally {
      setPending(false);
    }
  }

  // Checked against the trimmed length - that's what actually gets sent
  // (onSubmit uses text.trim()) and what the backend validates against.
  const overLimit = text.trim().length > MAX_LENGTH;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <label htmlFor="free-text-query" className="text-xs text-dim">
          Ask your own question
        </label>
        <span className={`font-mono text-xs tabular ${overLimit ? "text-alert" : "text-dim"}`}>
          {text.length}/{MAX_LENGTH}
        </span>
      </div>
      <div className="flex gap-2">
        <input
          id="free-text-query"
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setError(null);
          }}
          disabled={disabled || pending}
          placeholder="e.g. What is the capital of Germany?"
          className="flex-1 rounded border border-line bg-panel px-3 py-2 text-sm text-text placeholder:text-dim focus:border-dim focus:outline-none disabled:opacity-40"
        />
        <button
          type="submit"
          disabled={disabled || pending || !text.trim() || overLimit}
          className="rounded border border-line px-4 py-2 text-sm text-text transition-colors hover:border-dim disabled:opacity-40"
        >
          {pending ? "Asking…" : "Ask"}
        </button>
      </div>
      {error && <p className="text-xs text-alert">{error}</p>}
      {lastResponse && !error && (
        <p className="rounded border border-line bg-panel px-3 py-2 text-xs text-dim">
          {lastResponse}
        </p>
      )}
    </form>
  );
}
