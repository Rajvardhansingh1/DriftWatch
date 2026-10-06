"use client";

import Script from "next/script";
import { useCallback, useEffect, useRef } from "react";

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: { sitekey: string; callback: (token: string) => void }) => string;
    };
  }
}

// Loaded by Next's own (nonced) runtime, so 'strict-dynamic' allows it.
// The challenge iframe is allowed by `frame-src https://challenges.cloudflare.com`.
export function Turnstile({ onToken }: { onToken: (token: string) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const siteKey = process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY;

  const render = useCallback(() => {
    if (ref.current && window.turnstile && siteKey && !ref.current.hasChildNodes()) {
      window.turnstile.render(ref.current, { sitekey: siteKey, callback: onToken });
    }
  }, [onToken, siteKey]);

  useEffect(render, [render]);

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
