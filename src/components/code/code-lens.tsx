"use client";

import {
  animate,
  AnimatePresence,
  motion,
  useInView,
  useMotionValue,
  useReducedMotion,
  useTransform,
  type AnimationPlaybackControls,
} from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { duration, easeEntrance } from "@/lib/motion/tokens";

export type LensTarget = { line: number; label: string };

type Point = { x: number; y: number; bandTop: number; bandHeight: number };
type Geometry = {
  points: Point[];
  width: number;
  height: number;
  preLeft: number;
  preTop: number;
};

const SCALE = 1.6;
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Magnifier for <CodeWindow>. The lens shows a real second copy of the same code at
 * 1.6x, clipped to a circle and offset so the point under the lens centre is the point
 * shown magnified. Text is never blurred or distorted. Movement uses transforms only,
 * runs only while the window is in view, and is replaced by a static highlight of the
 * first target under reduced motion. Below 768px the lens is hidden; the line highlight
 * still moves and <LensCaption> shows the label in a bar under the code.
 */
export function CodeLens({ targets, size, copy }: { targets: LensTarget[]; size: number; copy: ReactNode }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const inView = useInView(rootRef, { amount: 0.35 });
  const [geometry, setGeometry] = useState<Geometry | null>(null);
  const [index, setIndex] = useState(0);
  const radius = size / 2;

  const cx = useMotionValue(0);
  const cy = useMotionValue(0);
  const bandY = useMotionValue(0);
  const lensTransform = useTransform(() => `translate(${cx.get() - radius}px, ${cy.get() - radius}px)`);
  const copyTransform = useTransform(
    () => `translate(${radius - cx.get() * SCALE}px, ${radius - cy.get() * SCALE}px) scale(${SCALE})`,
  );

  // Measure target lines relative to the code body (after fonts load, and on resize).
  useEffect(() => {
    const body = rootRef.current?.parentElement;
    const pre = body?.querySelector<HTMLElement>("[data-code-base]");
    if (!body || !pre || reduced) return;

    const measure = () => {
      const bodyRect = body.getBoundingClientRect();
      const preRect = pre.getBoundingClientRect();
      const chrome = body.offsetTop; // the lens may overlap the window title bar
      const points = targets.map((target) => {
        const row = pre.querySelector<HTMLElement>(`[data-line="${target.line}"]`);
        const text = row?.querySelector<HTMLElement>("[data-code-text]");
        if (!row || !text) return { x: radius, y: radius, bandTop: 0, bandHeight: 0 };
        const rowRect = row.getBoundingClientRect();
        const textRect = text.getBoundingClientRect();
        const rawX = textRect.left - bodyRect.left + Math.min(textRect.width, 260) / 2;
        const rawY = rowRect.top - bodyRect.top + rowRect.height / 2;
        return {
          x: Math.min(Math.max(rawX, radius + 4), bodyRect.width - radius - 4),
          y: Math.min(Math.max(rawY, radius - chrome + 4), bodyRect.height - radius),
          bandTop: rowRect.top - bodyRect.top,
          bandHeight: rowRect.height,
        };
      });
      setGeometry({
        points,
        width: bodyRect.width,
        height: bodyRect.height,
        preLeft: preRect.left - bodyRect.left,
        preTop: preRect.top - bodyRect.top,
      });
    };

    let observer: ResizeObserver | undefined;
    document.fonts.ready.then(() => {
      measure();
      observer = new ResizeObserver(measure);
      observer.observe(body);
    });
    body.setAttribute("data-lens", "on");
    return () => {
      observer?.disconnect();
      body.removeAttribute("data-lens");
    };
  }, [targets, radius, reduced]);

  // Place the lens on the current target whenever geometry changes.
  useEffect(() => {
    if (!geometry) return;
    const point = geometry.points[index] ?? geometry.points[0];
    cx.set(point.x);
    cy.set(point.y);
    bandY.set(point.bandTop);
    // Only re-place on geometry changes; the glide loop owns movement otherwise.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry]);

  // Glide between targets while in view.
  useEffect(() => {
    if (!geometry || reduced || !inView || geometry.points.length < 2) return;
    let active = true;
    let controls: AnimationPlaybackControls[] = [];
    const options = { duration: duration.lensGlide, ease: easeEntrance };

    (async () => {
      let next = (index + 1) % geometry.points.length;
      await sleep((duration.lensPause + duration.lensRead) * 1000);
      while (active) {
        const point = geometry.points[next];
        setIndex(next);
        rootRef.current?.dispatchEvent(new CustomEvent("lens:target", { detail: next, bubbles: true }));
        controls = [
          animate(cx, point.x, options),
          animate(cy, point.y, options),
          animate(bandY, point.bandTop, options),
        ];
        await Promise.all(controls.map((control) => control.finished));
        if (!active) break;
        await sleep((duration.lensPause + duration.lensRead) * 1000);
        next = (next + 1) % geometry.points.length;
      }
    })();

    return () => {
      active = false;
      controls.forEach((control) => control.stop());
    };
    // The loop restarts from the current index when visibility changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geometry, reduced, inView]);

  if (reduced) return null;

  const current = geometry?.points[index];
  const label = targets[index]?.label;

  return (
    // No z-index on this wrapper: it must not form a stacking context, so the band can sit
    // under the code (z-0) and the lens above it (z-[2]) within the code body.
    <div ref={rootRef} aria-hidden="true" className="pointer-events-none absolute inset-0">
      {geometry && current && (
        <>
          {/* Moving line highlight in the base code */}
          <motion.div
            className="absolute inset-x-0 z-0 border-l-2 border-primary bg-primary-soft"
            style={{ y: bandY, height: current.bandHeight }}
          />


          {/* The lens */}
          <motion.div
            className="absolute top-0 left-0 z-[2] hidden md:block"
            style={{ width: size, height: size, transform: lensTransform, willChange: inView ? "transform" : undefined }}
          >
            <div className="code-surface relative size-full overflow-hidden rounded-full">
              <motion.div
                className="absolute top-0 left-0 origin-top-left"
                style={{ width: geometry.width, height: geometry.height, transform: copyTransform }}
              >
                <motion.div
                  className="absolute inset-x-0 border-l-2 border-primary bg-primary-soft"
                  style={{ y: bandY, height: current.bandHeight }}
                />
                <pre className="absolute min-w-max" style={{ left: geometry.preLeft, top: geometry.preTop }}>
                  {copy}
                </pre>
              </motion.div>
              {/* Soft inner edge so the lens reads as glass */}
              <div className="absolute inset-0 rounded-full shadow-[inset_0_0_14px_rgba(21,25,35,0.14),inset_0_0_0_1px_rgba(21,25,35,0.06)]" />
            </div>
            {/* Rim, handle, caption */}
            <div className="absolute inset-0 rounded-full border-[3px] border-white shadow-[0_14px_34px_-10px_rgba(21,25,35,0.45),0_0_0_1px_rgba(21,25,35,0.1)]" />
            <div
              className="absolute h-11 w-[9px] origin-top rounded-full bg-[linear-gradient(180deg,#3a3f4b,#1a1e27)] shadow-[0_6px_14px_-6px_rgba(21,25,35,0.6)]"
              style={{ left: size * 0.84, top: size * 0.86, transform: "rotate(-45deg)" }}
            />
            <AnimatePresence mode="wait">
              <motion.span
                key={label}
                className="absolute bottom-2 left-1/2 rounded-full bg-foreground px-2.5 py-0.5 font-sans text-[0.6875rem] font-medium whitespace-nowrap text-white shadow-[0_4px_10px_-4px_rgba(21,25,35,0.5)]"
                style={{ x: "-50%" }}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -2 }}
                transition={{ duration: duration.micro, ease: easeEntrance }}
              >
                {label}
              </motion.span>
            </AnimatePresence>
          </motion.div>
        </>
      )}
    </div>
  );
}
