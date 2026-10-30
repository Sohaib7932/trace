"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import type { ScrollTrigger as ScrollTriggerType } from "gsap/ScrollTrigger";
import { loadGsap, markMotionFallback } from "@/lib/motion/gsap";
import { mq } from "@/lib/motion/tokens";

export type Step = { name: string; does: string; visual: ReactNode };

/** Scroll distance per step while pinned, as a percentage of the viewport height. */
const VH_PER_STEP = 85;

/**
 * The learning loop as sticky steps.
 * - ≥1024px with motion allowed: the block pins near the viewport centre and scroll advances the
 *   active step (~85vh each); the left rail fills with progress; the visual on the
 *   right swaps (incoming rises 24px and fades in, outgoing fades and lifts).
 * - Phones, tablets and reduced motion: an accordion; the visual sits inside the open item.
 * - No JS: every step is open with its visual, so all content is readable.
 * Step titles are buttons (aria-expanded, aria-controls) with roving focus (arrows, Home, End).
 */
export function StickySteps({ steps }: { steps: Step[] }) {
  const id = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLSpanElement>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const trigger = useRef<ScrollTriggerType | null>(null);
  const [active, setActive] = useState(0);
  const [pinned, setPinned] = useState(false);
  const count = steps.length;

  useEffect(() => {
    const root = rootRef.current;
    const fill = fillRef.current;
    if (!root || !fill || !matchMedia(mq.sequenceSteps).matches) return;

    let cancelled = false;
    let revert: (() => void) | undefined;
    loadGsap()
      .then(({ gsap, ScrollTrigger }) => {
        if (cancelled) return;
        const ctx = gsap.context(() => {
          gsap.matchMedia().add(mq.sequenceSteps, () => {
            setPinned(true);
            let last = 0;
            trigger.current = ScrollTrigger.create({
              trigger: root,
              // Pin with the block a little below centre, leaving the heading in view above
              start: "center 55%",
              end: `+=${count * VH_PER_STEP}%`,
              pin: true,
              anticipatePin: 1,
              invalidateOnRefresh: true,
              onUpdate(self) {
                fill.style.transform = `scaleY(${self.progress})`;
                const next = Math.min(count - 1, Math.floor(self.progress * count));
                if (next !== last) {
                  last = next;
                  setActive(next);
                }
              },
            });
            return () => {
              trigger.current = null;
              setPinned(false);
            };
          });
        }, root);
        ScrollTrigger.sort();
        ScrollTrigger.refresh();
        revert = () => ctx.revert();
      })
      .catch(markMotionFallback);

    return () => {
      cancelled = true;
      revert?.();
    };
  }, [count]);

  function select(index: number) {
    setActive(index);
    const st = trigger.current;
    if (st) {
      // Pinned: move the scroll position to that step so scroll and state agree.
      window.scrollTo({ top: st.start + ((index + 0.5) / count) * (st.end - st.start), behavior: "smooth" });
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const keys: Record<string, number> = {
      ArrowDown: (index + 1) % count,
      ArrowRight: (index + 1) % count,
      ArrowUp: (index - 1 + count) % count,
      ArrowLeft: (index - 1 + count) % count,
      Home: 0,
      End: count - 1,
    };
    if (!(event.key in keys)) return;
    event.preventDefault();
    buttons.current[keys[event.key]]?.focus();
  }

  return (
    <div ref={rootRef} className="steps" data-pinned={pinned ? "" : undefined}>
      <div className="steps-list">
        {/* Progress rail */}
        <span aria-hidden="true" className="steps-rail">
          <span
            ref={fillRef}
            className="steps-rail-fill"
            style={pinned ? undefined : { transform: `scaleY(${(active + 1) / count})` }}
          />
        </span>

        <ol>
          {steps.map((step, index) => {
            const open = index === active;
            return (
              <li key={step.name} className="steps-item" data-open={open ? "" : undefined}>
                <h3>
                  <button
                    ref={(element) => {
                      buttons.current[index] = element;
                    }}
                    id={`${id}-tab-${index}`}
                    type="button"
                    aria-expanded={open}
                    aria-controls={`${id}-panel-${index}`}
                    tabIndex={open ? 0 : -1}
                    onClick={() => select(index)}
                    onKeyDown={(event) => onKeyDown(event, index)}
                    className="steps-button"
                  >
                    <span className="steps-number">0{index + 1}</span>
                    <span className="steps-name">{step.name}</span>
                  </button>
                </h3>
                <div id={`${id}-panel-${index}`} role="region" aria-labelledby={`${id}-tab-${index}`} className="steps-panel">
                  <div className="steps-panel-inner">
                    <p className="steps-does">{step.does}</p>
                    <div className="steps-inline-visual">{step.visual}</div>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      </div>

      {/* Desktop with motion: the large visual for the active step */}
      <div className="steps-visuals">
        {steps.map((step, index) => (
          <div
            key={step.name}
            className="steps-visual"
            data-state={index === active ? "active" : index < active ? "past" : "next"}
            aria-hidden={index !== active}
            inert={index !== active}
          >
            {step.visual}
          </div>
        ))}
      </div>
    </div>
  );
}
