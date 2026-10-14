"use client";

import dynamic from "next/dynamic";
import { Component, useEffect, useState, type ReactNode } from "react";
import { Skeleton } from "./Skeleton";

const HeroScene = dynamic(() => import("./HeroScene"), {
  ssr: false,
  loading: () => <Skeleton label="Loading 3D view" className="h-full w-full" />,
});

function canUseWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    // Release the probe context so it does not count against the browser's context limit.
    (gl?.getExtension("WEBGL_lose_context") as { loseContext(): void } | null | undefined)?.loseContext();
    return Boolean(gl);
  } catch {
    return false;
  }
}

function StaticHero() {
  // eslint-disable-next-line @next/next/no-img-element
  return <img src="/hero-fallback.svg" alt="" className="h-full w-full" />;
}

// A WebGL/three.js failure must degrade to the still image, never blank the page.
class SceneBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <StaticHero /> : this.props.children;
  }
}

export function HeroVisual() {
  const [mode, setMode] = useState<"pending" | "3d" | "static">("pending");

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    let timer: number | undefined;
    const decide = () => setMode(!mq.matches && canUseWebGL() ? "3d" : "static");
    // The still image is what first paints (and what the server renders). The animated scene joins a moment after the page has
    // loaded, so a continuously changing canvas does not hold up the page's first impression.
    const start = () => {
      timer = window.setTimeout(decide, 1500);
    };
    if (mq.matches) decide();
    else if (document.readyState === "complete") start();
    else window.addEventListener("load", start, { once: true });
    const onChange = () => decide();
    mq.addEventListener("change", onChange);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("load", start);
      mq.removeEventListener("change", onChange);
    };
  }, []);

  if (mode === "pending" || mode === "static") return <StaticHero />;
  return (
    <SceneBoundary>
      <HeroScene onContextLost={() => setMode("static")} />
    </SceneBoundary>
  );
}
