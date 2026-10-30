"use client";

import { Check } from "lucide-react";
import { useEffect, useId, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import type { ScrollTrigger as ScrollTriggerType } from "gsap/ScrollTrigger";
import { loadGsap, markMotionFallback } from "@/lib/motion/gsap";
import { mq } from "@/lib/motion/tokens";

export type Step = {
  name: string;
  /** One-line teaser shown on collapsed rows (accordion). */
  teaser: string;
  does: string;
  /** Lucide icon element (rendered on the server and passed in). */
  icon: ReactNode;
  /** Visual for the desktop panel. */
  visual: ReactNode;
  /**
   * Visual for the accordion: always a separately created element, never the same
   * element as `visual` (one server element rendered twice trips React DevTools).
   */
  compact: ReactNode;
};

/** Scroll distance per step while the block is stuck, as a percentage of the viewport height. */
const VH_PER_STEP = 70;
/** Keep the stuck block and scrolled-to rows clear of the floating nav. */
const NAV_CLEARANCE = 92;
/** Matches the 350ms open transition in globals.css. */
const OPEN_MS = 350;

/**
 * The learning loop as steps.
 *
 * ≥1024px with motion allowed: a fixed-height two-column block, max(520px, min(78vh, 680px)),
 * is CSS-sticky (vertically centred) inside a track of exactly that height plus 70vh per
 * step. Scroll progress drives the active step; the visual swaps inside a fixed-size panel.
 *
 * Below 1024px and with reduced motion: a compact, tap-driven accordion. Each row has an
 * icon chip, title, teaser and number; one row opens at a time into a card with the
 * description and a compact visual. A line through the chips fills down to the active one.
 * Without JS: every step open with its visual.
 */
export function StickySteps({ steps }: { steps: Step[] }) {
  const id = useId();
  const trackRef = useRef<HTMLDivElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const fillRef = useRef<HTMLSpanElement>(null);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const items = useRef<(HTMLLIElement | null)[]>([]);
  const trigger = useRef<ScrollTriggerType | null>(null);
  const [active, setActive] = useState(0);
  const [scrubbing, setScrubbing] = useState(false);
  const count = steps.length;

  useEffect(() => {
    const track = trackRef.current;
    const root = rootRef.current;
    const fill = fillRef.current;
    if (!track || !root || !fill || !matchMedia(mq.sequenceSteps).matches) return;

    let cancelled = false;
    let revert: (() => void) | undefined;
    loadGsap()
      .then(({ gsap, ScrollTrigger }) => {
        if (cancelled) return;
        const ctx = gsap.context(() => {
          gsap.matchMedia().add(mq.sequenceSteps, () => {
            setScrubbing(true);
            setActive((current) => (current < 0 ? 0 : current));
            let last = 0;
            let top = NAV_CLEARANCE;
            const place = () => {
              top = Math.max(NAV_CLEARANCE, Math.round((window.innerHeight - root.offsetHeight) / 2 + 24));
              root.style.setProperty("--steps-top", `${top}px`);
            };
            place();
            trigger.current = ScrollTrigger.create({
              trigger: track,
              start: () => `top ${top}px`,
              end: () => `bottom ${top + root.offsetHeight}px`,
              invalidateOnRefresh: true,
              onRefreshInit: place,
              onUpdate(self) {
                fill.style.transform = `scaleY(${self.progress})`;
                const next = Math.min(count - 1, Math.floor(self.progress * count));
                if (next !== last) {
                  last = next;
                  setActive(next);
                }
              },
            });
            const refresh = () => ScrollTrigger.refresh();
            window.addEventListener("load", refresh);
            return () => {
              window.removeEventListener("load", refresh);
              trigger.current = null;
              setScrubbing(false);
              root.style.removeProperty("--steps-top");
              fill.style.removeProperty("transform");
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

  /** Accordion: after a row opens, bring it into view if it ended up off-screen. */
  function revealRow(index: number) {
    const reduced = matchMedia(mq.reduced).matches;
    window.setTimeout(
      () => {
        const row = items.current[index];
        if (!row) return;
        const rect = row.getBoundingClientRect();
        const offTop = rect.top < NAV_CLEARANCE;
        const offBottom = rect.bottom > window.innerHeight - 16;
        if (!offTop && !offBottom) return;
        // Align the row's top just below the floating nav (also when it is taller than the screen).
        const target = window.scrollY + rect.top - NAV_CLEARANCE;
        window.scrollTo({ top: target, behavior: reduced ? "auto" : "smooth" });
      },
      reduced ? 0 : OPEN_MS + 20,
    );
  }

  function select(index: number) {
    const st = trigger.current;
    if (st) {
      // Desktop: scroll to that step so scroll and state agree.
      setActive(index);
      window.scrollTo({ top: st.start + ((index + 0.5) / count) * (st.end - st.start), behavior: "smooth" });
      return;
    }
    // Accordion: toggle; opening one closes the other.
    const opening = index !== active;
    setActive(opening ? index : -1);
    if (opening) revealRow(index);
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

  // Roving focus: the open row is tabbable, or the first row when none is open.
  const tabbable = active < 0 ? 0 : active;

  return (
    <div
      ref={trackRef}
      className="steps-track"
      style={{ "--steps-scroll": `${count * VH_PER_STEP}vh` } as CSSProperties}
    >
      <div ref={rootRef} className="steps" data-scrubbing={scrubbing ? "" : undefined} data-reveal-stagger="card">
        <div className="steps-list">
          {/* Desktop progress line (scroll-driven) */}
          <span aria-hidden="true" className="steps-rail">
            <span
              ref={fillRef}
              className="steps-rail-fill"
              style={scrubbing ? undefined : { transform: `scaleY(${(active + 1) / count})` }}
            />
          </span>

          <ol className="steps-rows">
            {steps.map((step, index) => {
              const open = index === active;
              const state = open ? "active" : active >= 0 && index < active ? "done" : "todo";
              return (
                <li
                  key={step.name}
                  ref={(element) => {
                    items.current[index] = element;
                  }}
                  className="steps-item"
                  data-reveal-item
                  data-open={open ? "" : undefined}
                  data-state={state}
                >
                  {/* Accordion progress: from this chip's centre to the next chip's centre */}
                  {index < count - 1 && (
                    <span aria-hidden="true" className="steps-seg">
                      <span className="steps-seg-fill" data-filled={active >= 0 && index < active ? "" : undefined} />
                    </span>
                  )}
                  <h3>
                    <button
                      ref={(element) => {
                        buttons.current[index] = element;
                      }}
                      id={`${id}-tab-${index}`}
                      type="button"
                      aria-expanded={open}
                      aria-controls={`${id}-panel-${index}`}
                      tabIndex={index === tabbable ? 0 : -1}
                      onClick={() => select(index)}
                      onKeyDown={(event) => onKeyDown(event, index)}
                      className="steps-button"
                    >
                      <span aria-hidden="true" className="steps-chip">
                        {state === "done" ? <Check className="size-4" strokeWidth={2.25} /> : step.icon}
                      </span>
                      <span className="steps-heading">
                        <span className="steps-name">{step.name}</span>
                        <span className="steps-teaser-wrap">
                          <span className="steps-teaser">{step.teaser}</span>
                        </span>
                      </span>
                      <span className="steps-number">0{index + 1}</span>
                      {state === "done" && <span className="sr-only"> (done)</span>}
                    </button>
                  </h3>
                  <div
                    id={`${id}-panel-${index}`}
                    role="region"
                    aria-labelledby={`${id}-tab-${index}`}
                    className="steps-panel"
                  >
                    <div className="steps-panel-inner">
                      <p className="steps-does">{step.does}</p>
                      <div className="steps-inline-visual">{step.compact}</div>
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        </div>

        {/* Desktop with motion: one tall panel, its size fixed; the active visual swaps inside */}
        <div className="steps-stage" data-reveal-item style={{ "--step": Math.max(active, 0) } as CSSProperties}>
          <div aria-hidden="true" className="steps-mesh" />
          {steps.map((step, index) => (
            <div
              key={step.name}
              className="steps-visual"
              data-state={index === active ? "active" : index < active ? "past" : "next"}
              aria-hidden={index !== active}
              inert={index !== active}
            >
              <div className="steps-card">{step.visual}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
