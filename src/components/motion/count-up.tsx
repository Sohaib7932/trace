"use client";

import { useEffect, useRef } from "react";

const DURATION = 600;

/**
 * A number that counts up once when it first appears (under 700ms). The final value is in the
 * markup from the start, so screen readers, no-JS and reduced motion get it immediately.
 */
export function CountUp({ value, className = "" }: { value: number; className?: string }) {
  const node = useRef<HTMLSpanElement>(null);
  const played = useRef(false);
  useEffect(() => {
    const element = node.current;
    if (!element || played.current) return;
    played.current = true;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;
    if (reduced || value <= 0) return;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / DURATION);
      element.textContent = String(Math.round(value * (1 - (1 - t) ** 3)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(frame); element.textContent = String(value); };
  }, [value]);
  return <span ref={node} className={`tabular-nums ${className}`}>{value}</span>;
}
