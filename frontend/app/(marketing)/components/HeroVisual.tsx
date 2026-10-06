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
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function StaticHero() {
  // eslint-disable-next-line @next/next/no-img-element
  return <img src="/hero-fallback.svg" alt="" className="h-full w-full" />;
}

// A WebGL/r3f failure must degrade to the still image, never blank the page.
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
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setMode(!reduce && canUseWebGL() ? "3d" : "static");
  }, []);

  if (mode === "pending") return <Skeleton label="Loading 3D view" className="h-full w-full" />;
  if (mode === "static") return <StaticHero />;
  return (
    <SceneBoundary>
      <HeroScene />
    </SceneBoundary>
  );
}
