"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";

const COUNT = 1400;

// DESIGN.md tokens: --mk-muted / --mk-accent per theme.
const PALETTE = {
  light: { base: 0x4b5562, accent: 0x8a5300 },
  dark: { base: 0x8a97a6, accent: 0xf2b84b },
};

// A cloud of answers. Every seventh point drifts away from the cluster and
// back, the way a slice of outputs drifts from the baseline.
export default function HeroScene({ onContextLost }: { onContextLost?: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const lost = useRef(onContextLost);
  lost.current = onContextLost;

  useEffect(() => {
    const el = host.current;
    if (!el) return;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const canvas = renderer.domElement;
    const onLost = (e: Event) => {
      e.preventDefault();
      lost.current?.();
    };
    canvas.addEventListener("webglcontextlost", onLost);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.z = 4.2;
    const scene = new THREE.Scene();

    const positions = new Float32Array(COUNT * 3);
    const colors = new Float32Array(COUNT * 3);
    for (let i = 0; i < COUNT; i++) {
      const r = 1.6 * Math.cbrt(Math.random());
      const t = Math.random() * Math.PI * 2;
      const u = Math.acos(2 * Math.random() - 1);
      positions[i * 3] = r * Math.sin(u) * Math.cos(t);
      positions[i * 3 + 1] = r * Math.sin(u) * Math.sin(t);
      positions[i * 3 + 2] = r * Math.cos(u);
    }
    const origin = positions.slice();
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
    const material = new THREE.PointsMaterial({ size: 0.03, vertexColors: true, sizeAttenuation: true });
    const points = new THREE.Points(geometry, material);
    scene.add(points);

    // THREE.Color(hex) converts sRGB -> linear working space; the renderer converts back for display.
    const dark = window.matchMedia("(prefers-color-scheme: dark)");
    const c = new THREE.Color();
    const paint = () => {
      const p = PALETTE[dark.matches ? "dark" : "light"];
      for (let i = 0; i < COUNT; i++) {
        c.setHex(i % 7 === 0 ? p.accent : p.base);
        colors[i * 3] = c.r;
        colors[i * 3 + 1] = c.g;
        colors[i * 3 + 2] = c.b;
      }
      geometry.attributes.color.needsUpdate = true;
    };
    paint();
    dark.addEventListener("change", paint);

    const resize = () => {
      const w = el.clientWidth || 1;
      const h = el.clientHeight || 1;
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.setSize(w, h, false);
      renderer.domElement.style.cssText = "width:100%;height:100%;display:block";
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    // Elapsed time only counts while running, so resuming does not jump.
    let elapsed = 0;
    let last = 0;
    let raf = 0;
    let onScreen = true;
    const frame = (now: number) => {
      elapsed += (now - last) / 1000;
      last = now;
      points.rotation.y = elapsed * 0.05;
      const amount = (Math.sin((elapsed * 2 * Math.PI) / 16) + 1) / 2;
      for (let i = 0; i < COUNT; i += 7) positions[i * 3] = origin[i * 3] + amount * 0.9;
      geometry.attributes.position.needsUpdate = true;
      renderer.render(scene, camera);
      raf = requestAnimationFrame(frame);
    };
    const sync = () => {
      const run = onScreen && !document.hidden;
      if (run && !raf) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      } else if (!run && raf) {
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };
    const io = new IntersectionObserver((e) => {
      onScreen = e[e.length - 1].isIntersecting;
      sync();
    });
    io.observe(el);
    document.addEventListener("visibilitychange", sync);
    sync();

    return () => {
      cancelAnimationFrame(raf);
      raf = 0;
      io.disconnect();
      ro.disconnect();
      document.removeEventListener("visibilitychange", sync);
      dark.removeEventListener("change", paint);
      geometry.dispose();
      material.dispose();
      canvas.removeEventListener("webglcontextlost", onLost);
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, []);

  return <div ref={host} aria-hidden="true" className="h-full w-full" />;
}
