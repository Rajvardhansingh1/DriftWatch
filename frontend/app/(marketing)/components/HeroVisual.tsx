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
    const decide = () => setMode(!mq.matches && canUseWebGL() ? "3d" : "static");
    decide();
    mq.addEventListener("change", decide);
    return () => mq.removeEventListener("change", decide);
  }, []);

  if (mode === "pending")
    return (
      <div className="relative h-full w-full">
        <Skeleton label="Loading 3D view" className="h-full w-full" />
        <noscript>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/hero-fallback.svg" alt="" className="absolute inset-0 h-full w-full" />
        </noscript>
      </div>
    );
  if (mode === "static") return <StaticHero />;
  return (
    <SceneBoundary>
      <HeroScene />
    </SceneBoundary>
  );
}
