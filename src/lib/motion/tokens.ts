/**
 * Shared motion tokens (CLAUDE.md §7). Every animation on the site uses these.
 * The CSS custom properties in globals.css (--ease-out, --ease-ui, --dur-*) mirror
 * these values for CSS-driven transitions; keep both in sync.
 */

/** cubic-bezier(.22,1,.36,1): entrances, reveals, scroll sequences. */
export const easeEntrance = [0.22, 1, 0.36, 1] as const;
/** cubic-bezier(.2,.8,.2,1): hovers and small UI state changes. */
export const easeHover = [0.2, 0.8, 0.2, 1] as const;

/** Durations in seconds. */
export const duration = {
  micro: 0.18, // hovers, presses (120–220ms)
  state: 0.3, // UI state transitions (180–350ms)
  entrance: 0.65, // section entrances (400–700ms)
  card: 0.8, // card entrances on scroll
  cardInnerDelay: 0.3, // inner visual starts this long after its card
  cardInner: 0.35, // one inner part (code line, diff row, evidence row)
  reducedFade: 0.15, // reduced motion: a quick opacity fade only
  word: 0.7, // one heading word
  accentWord: 0.9, // the accent word, slightly longer
  reveal: 0.8, // large visual reveals (500–900ms)
  connector: 0.5, // flow-diagram connector draw (400–600ms)
  lensGlide: 0.75, // magnifier glide between targets (600–900ms)
  lensPause: 0.4, // magnifier pause on a target
  lensRead: 0.9, // extra dwell so the lens caption can be read (pause + read = 1.3s)
  stepSwap: 0.55, // sticky-steps visual swap (500–600ms)
} as const;

/** Stagger intervals in seconds. */
export const stagger = {
  words: 0.07, // 60–80ms
  cards: 0.12, // 100–140ms, left to right
  cardsMobile: 0.07, // 60–80ms on phones
  inner: 0.035, // 30–40ms between inner parts (inner pass stays under 600ms)
  branches: 0.12,
} as const;

/** Reveal variants: the "from" state. The CSS in globals.css must match. */
export const revealFrom = {
  up: { y: 24, scale: 1 },
  card: { y: 40, scale: 0.97 },
  fade: { y: 0, scale: 1 },
} as const;

export type RevealVariant = keyof typeof revealFrom;

/** Cards rise less on phones. */
export const cardRiseMobile = 24;

/** Cards trigger when their top reaches ~88% of the viewport height. */
export const cardTrigger = "0px 0px -12% 0px";

/** Scroll-linked depth inside cards (desktop only): max drift and catch-up time (scrub). */
export const parallax = { range: 14, scrub: 0.5 } as const;

/** Heading word blur: full on desktop, reduced on phones. */
export const wordBlur = { desktop: 12, mobile: 6 } as const;
export const wordRise = 18;

/** Breakpoints the motion system cares about. */
export const mq = {
  reduced: "(prefers-reduced-motion: reduce)",
  mobile: "(max-width: 767px)",
  /** Pinned, scrubbed GSAP sequences only run here. */
  sequenceDevice: "(min-width: 768px) and (prefers-reduced-motion: no-preference)",
  sequenceSteps: "(min-width: 1024px) and (prefers-reduced-motion: no-preference)",
  /** Card parallax: desktop with motion allowed. */
  parallax: "(min-width: 1024px) and (prefers-reduced-motion: no-preference)",
} as const;
