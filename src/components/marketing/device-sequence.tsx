"use client";

import { animate, inView } from "motion";
import { useEffect, useRef, useState } from "react";
import { loadGsap, markMotionFallback } from "@/lib/motion/gsap";
import { duration, easeEntrance, mq } from "@/lib/motion/tokens";
import { DevicePanel } from "./device-panel";
import { LessonDemo } from "./lesson-demo";
import { LightStreaks } from "./light-streaks";

/** Approximate height of the floating nav, kept clear above the pinned stage. */
const NAV_CLEARANCE = 76;
/** Never shrink the device below this, so the code stays readable. */
const MIN_SETTLE_SCALE = 0.7;

/**
 * The hero's signature scroll sequence: one pinned, scrubbed GSAP timeline.
 *  A (0–25%)   tilted device rises while the tilt relaxes
 *  B (25–50%)  device flattens fully, shadow deepens, step tracker moves Read → Predict
 *  C (50–75%)  background panel scales in behind it; bezel eases graphite → light
 *  D (75–100%) panel expands to the canvas width, device settles at ≥0.7 scale
 *
 * The server HTML is the final, static composition (light bezel on the panel). The
 * tilted "from" pose is applied by CSS only under html.js, ≥768px, motion allowed.
 * Phones and reduced motion: no pin, no 3D, just a 0.96 → 1 scale-in on view.
 */
export function DeviceSequence() {
  const stageRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const [holdRead, setHoldRead] = useState(false);

  useEffect(() => {
    const stage = stageRef.current;
    const frame = frameRef.current;
    if (!stage || !frame) return;

    // Phones (motion allowed): simple scale-in, no pin.
    if (matchMedia(mq.mobile).matches) {
      if (matchMedia(mq.reduced).matches) {
        frame.setAttribute("data-revealed", "");
        return;
      }
      const stop = inView(frame, () => {
        stop();
        animate(
          frame,
          { opacity: [0, 1], transform: ["scale(0.96)", "scale(1)"] },
          { duration: duration.entrance, ease: easeEntrance },
        ).finished.then(() => {
          frame.setAttribute("data-revealed", "");
          requestAnimationFrame(() => {
            frame.style.removeProperty("opacity");
            frame.style.removeProperty("transform");
          });
        });
      });
      return () => stop();
    }

    // Desktop with reduced motion: static composition, and GSAP is never downloaded.
    if (!matchMedia(mq.sequenceDevice).matches) return;

    let cancelled = false;
    let revert: (() => void) | undefined;
    const onAnchorClick: { current?: (event: MouseEvent) => void } = {};

    loadGsap()
      .then(({ gsap, ScrollTrigger }) => {
        if (cancelled) return;
        const ctx = gsap.context(() => {
          const mm = gsap.matchMedia();
          mm.add(mq.sequenceDevice, () => {
            const q = gsap.utils.selector(stage);
            const panel = q(".device-panel")[0];
            const bezelDark = q(".bezel-dark")[0];
            const shadow = q(".device-shadow")[0];
            const streaks = q(".device-streaks")[0];
            const vh = () => window.innerHeight;
            const fit = () => Math.min(1, (vh() - NAV_CLEARANCE - 56) / frame.offsetHeight);
            const settle = () => Math.max(MIN_SETTLE_SCALE, fit() * 0.74);

            let held = true;
            setHoldRead(true);

            const tl = gsap.timeline({
              defaults: { ease: "none" },
              scrollTrigger: {
                trigger: stage,
                start: "top top",
                end: "+=275%",
                pin: true,
                scrub: 0.8,
                anticipatePin: 1,
                invalidateOnRefresh: true,
                refreshPriority: 1,
                onUpdate(self) {
                  const hold = self.progress < 0.42;
                  if (hold !== held) {
                    held = hold;
                    setHoldRead(hold);
                  }
                },
              },
            });

            // Phase A: rise while the tilt begins to relax
            tl.fromTo(
              frame,
              { rotateX: 52, rotateZ: -4, scale: () => fit() * 1.08, y: () => vh() * 0.08 },
              { rotateX: 24, rotateZ: -2, scale: () => fit() * 1.04, y: () => vh() * 0.03, duration: 0.25 },
              0,
            )
              .fromTo(streaks, { y: () => vh() * 0.08, opacity: 1 }, { y: () => vh() * 0.02, opacity: 0.7, duration: 0.25 }, 0)
              // Phase B: flatten fully, deepen the shadow
              .to(frame, { rotateX: 0, rotateZ: 0, scale: () => fit(), y: 0, duration: 0.25 }, 0.25)
              .fromTo(shadow, { opacity: 0.2 }, { opacity: 1, duration: 0.25 }, 0.25)
              .to(streaks, { y: () => -vh() * 0.04, opacity: 0, duration: 0.3 }, 0.25)
              // Phase C: panel scales in behind; bezel eases from graphite to light
              .fromTo(
                panel,
                { opacity: 0, scale: 0.8, yPercent: 4 },
                { opacity: 1, scale: 0.88, yPercent: 1.5, duration: 0.25 },
                0.5,
              )
              .fromTo(bezelDark, { opacity: 1 }, { opacity: 0, duration: 0.25 }, 0.5)
              // Phase D: panel to full width, device settles (never below 0.7)
              .to(panel, { scale: 1, yPercent: 0, duration: 0.25 }, 0.75)
              // The frame pivots on its top edge (for the tilt), so shift it down by half the
              // height it loses: it shrinks around its own centre and stays centred on the panel.
              .to(
                frame,
                {
                  scale: () => settle(),
                  y: () => (frame.offsetHeight * (fit() - settle())) / 2,
                  duration: 0.25,
                },
                0.75,
              );

            // "Try a lesson" / "Try Trace" (#demo) land where the device is flat and usable.
            onAnchorClick.current = (event: MouseEvent) => {
              const link = (event.target as Element | null)?.closest?.('a[href="#demo"]');
              const trigger = tl.scrollTrigger;
              if (!link || !trigger) return;
              event.preventDefault();
              window.scrollTo({ top: trigger.start + (trigger.end - trigger.start) * 0.5, behavior: "smooth" });
            };
            document.addEventListener("click", onAnchorClick.current);

            return () => {
              if (onAnchorClick.current) document.removeEventListener("click", onAnchorClick.current);
              setHoldRead(false);
            };
          });
        }, stage);
        ScrollTrigger.sort();
        ScrollTrigger.refresh();
        revert = () => ctx.revert();
      })
      .catch(markMotionFallback);

    return () => {
      cancelled = true;
      revert?.();
    };
  }, []);

  return (
    <div id="demo" ref={stageRef} className="device-stage">
      <h2 className="sr-only">Try a sample lesson</h2>
      <DevicePanel />
      <div className="device-perspective">
        <div className="device-box">
          <div className="device-streaks" aria-hidden="true">
            <LightStreaks />
          </div>
          <div aria-hidden="true" className="showcase-glow" />
          <div ref={frameRef} className="device-frame">
            <div aria-hidden="true" className="device-shadow" />
            <div aria-hidden="true" className="bezel-light" />
            <div aria-hidden="true" className="bezel-dark" />
            <div aria-hidden="true" className="device-notch">
              <span className="device-notch-pill" />
              <span className="device-notch-dot" />
            </div>
            <div className="device-screen">
              <LessonDemo railHold={holdRead ? 0 : undefined} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
