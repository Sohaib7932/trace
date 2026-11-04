"use client";

import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

/**
 * Scroll progress as CSS variables, with no React re-render per frame.
 *  - `--p` (0 to 1) on the element, and `data-step` (0 to steps-1) when `steps` is set.
 *  - mode "track": a tall element holding a sticky stage; p runs while the stage is pinned.
 *    (Below 768px the stage is not pinned, so p follows the element crossing the screen.)
 *  - mode "section": p runs while the element crosses the viewport.
 * Reduced motion sets the final state (`--p: 1`, last step) and never listens to scroll.
 */
export function ScrollVars({ mode = "section", steps = 0, className = "", style, children }: {
  mode?: "track" | "section";
  steps?: number;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  const node = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = node.current;
    if (!element) return;
    const set = (p: number) => {
      element.style.setProperty("--p", p.toFixed(4));
      if (steps > 0) {
        const step = String(Math.min(steps - 1, Math.floor(p * steps)));
        if (element.dataset.step !== step) element.dataset.step = step;
      }
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { set(1); return; }
    const small = window.matchMedia("(max-width: 767px)");
    let near = true;
    let frame = 0;
    const update = () => {
      frame = 0;
      const rect = element.getBoundingClientRect();
      const vh = window.innerHeight;
      const pinned = mode === "track" && !small.matches && rect.height > vh;
      const raw = pinned ? -rect.top / (rect.height - vh) : (vh - rect.top) / (vh + rect.height);
      set(Math.min(1, Math.max(0, raw)));
    };
    const schedule = () => { if (near && !frame) frame = requestAnimationFrame(update); };
    const observer = new IntersectionObserver(([entry]) => { near = entry.isIntersecting; schedule(); }, { rootMargin: "200px 0px" });
    observer.observe(element);
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    update();
    return () => { observer.disconnect(); window.removeEventListener("scroll", schedule); window.removeEventListener("resize", schedule); cancelAnimationFrame(frame); };
  }, [mode, steps]);
  return <div ref={node} className={className} style={style} data-step={steps > 0 ? "0" : undefined}>{children}</div>;
}
