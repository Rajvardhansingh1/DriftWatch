"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";
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

export function HeroVisual() {
  const [mode, setMode] = useState<"pending" | "3d" | "static">("pending");

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    setMode(!reduce && canUseWebGL() ? "3d" : "static");
  }, []);

  if (mode === "pending") return <Skeleton label="Loading 3D view" className="h-full w-full" />;
  if (mode === "static") {
    // eslint-disable-next-line @next/next/no-img-element
    return <img src="/hero-fallback.svg" alt="" className="h-full w-full" />;
  }
  return <HeroScene />;
}
