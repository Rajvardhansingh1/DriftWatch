"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef } from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (
        el: HTMLElement,
        opts: {
          sitekey: string;
          callback: (token: string) => void;
          "expired-callback"?: () => void;
          "error-callback"?: () => void;
        },
      ) => string;
      reset: (widgetId?: string) => void;
      remove: (widgetId?: string) => void;
    };
  }
}

// Loaded by Next's own (nonced) runtime, so 'strict-dynamic' allows it.
// The challenge iframe is allowed by `frame-src https://challenges.cloudflare.com`.
// Tokens are single-use and expire, so the token is cleared on expiry/error and
// the widget is reset whenever `resetKey` changes (e.g. after a failed submit).
export function Turnstile({ onToken, resetKey = 0 }: { onToken: (token: string) => void; resetKey?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const widgetId = useRef<string | undefined>(undefined);
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;

  const render = useCallback(() => {
    if (ref.current && window.turnstile && siteKey && widgetId.current === undefined) {
      widgetId.current = window.turnstile.render(ref.current, {
        sitekey: siteKey,
        callback: onToken,
        "expired-callback": () => onToken(""),
        "error-callback": () => onToken(""),
      });
    }
  }, [onToken, siteKey]);

  useEffect(render, [render]);

  useEffect(() => {
    if (resetKey > 0 && widgetId.current !== undefined) window.turnstile?.reset(widgetId.current);
  }, [resetKey]);

  useEffect(
    () => () => {
      if (widgetId.current !== undefined) window.turnstile?.remove(widgetId.current);
      widgetId.current = undefined;
    },
    [],
  );

  if (!siteKey) return null;
  return (
    <>
      <Script
        src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
        strategy="afterInteractive"
        onLoad={render}
      />
      <div ref={ref} />
    </>
  );
}
