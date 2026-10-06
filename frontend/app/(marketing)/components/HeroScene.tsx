"use client";

import { Canvas, useFrame } from "@react-three/fiber";
import { useMemo, useRef } from "react";
import type { Points } from "three";

const COUNT = 1400;

type RGB = [number, number, number];

// DESIGN.md tokens, picked once at mount: --mk-muted / --mk-accent per theme.
const PALETTE: Record<"light" | "dark", { base: RGB; accent: RGB }> = {
  light: { base: [0x4b / 255, 0x55 / 255, 0x62 / 255], accent: [0x8a / 255, 0x53 / 255, 0x00 / 255] },
  dark: { base: [0x8a / 255, 0x97 / 255, 0xa6 / 255], accent: [0xf2 / 255, 0xb8 / 255, 0x4b / 255] },
};

// A cloud of answers. Every seventh point drifts away from the cluster and
// back, the way a slice of outputs drifts from the baseline.
function Cloud({ base, accent }: { base: RGB; accent: RGB }) {
  const ref = useRef<Points>(null);
  const { positions, origin, colors, drifting } = useMemo(() => {
    const positions = new Float32Array(COUNT * 3);
    const colors = new Float32Array(COUNT * 3);
    const drifting = new Uint8Array(COUNT);
    for (let i = 0; i < COUNT; i++) {
      const r = 1.6 * Math.cbrt(Math.random());
      const t = Math.random() * Math.PI * 2;
      const u = Math.acos(2 * Math.random() - 1);
      positions[i * 3] = r * Math.sin(u) * Math.cos(t);
      positions[i * 3 + 1] = r * Math.sin(u) * Math.sin(t);
      positions[i * 3 + 2] = r * Math.cos(u);
      drifting[i] = i % 7 === 0 ? 1 : 0;
      colors.set(drifting[i] ? accent : base, i * 3);
    }
    return { positions, origin: positions.slice(), colors, drifting };
  }, [base, accent]);

  useFrame(({ clock }) => {
    const points = ref.current;
    if (!points) return;
    const t = clock.getElapsedTime();
    points.rotation.y = t * 0.05;
    const amount = (Math.sin(t * 0.4) + 1) / 2;
    const attr = points.geometry.attributes.position;
    const arr = attr.array as Float32Array;
    for (let i = 0; i < COUNT; i++) {
      if (drifting[i]) arr[i * 3] = origin[i * 3] + amount * 0.9;
    }
    attr.needsUpdate = true;
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
      </bufferGeometry>
      <pointsMaterial size={0.03} vertexColors sizeAttenuation />
    </points>
  );
}

export default function HeroScene() {
  const { base, accent } = useMemo(
    () => PALETTE[window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"],
    [],
  );
  return (
    <div aria-hidden="true" className="h-full w-full">
      <Canvas camera={{ position: [0, 0, 4.2], fov: 45 }} dpr={[1, 2]}>
        <Cloud base={base} accent={accent} />
      </Canvas>
    </div>
  );
}
