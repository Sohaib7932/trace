"use client";

import { animate, inView, scroll } from "motion";
import { useEffect } from "react";
import {
  cardRiseMobile,
  cardTrigger,
  duration,
  easeEntrance,
  mq,
  parallax,
  revealFrom,
  stagger,
  lineBlurAbove,
  wordBlur,
  wordOpaqueAt,
  wordRise,
  type RevealVariant,
} from "@/lib/motion/tokens";

/**
 * One small client runtime for every scroll reveal on the page.
 *
 * Server Components mark content with <Reveal> / <SplitHeading> / data attributes. CSS
 * hides it only under html.js; this runtime animates it in once (Motion inView + animate),
 * then sets data-revealed and removes every inline style, so the final DOM is exactly
 * the default CSS state. It also runs the desktop-only scroll-linked depth inside cards.
 */

const TARGETS = "[data-reveal], [data-reveal-stagger], [data-split]";
const HEADING_TRIGGER = "0px 0px -15% 0px"; // fires at ~85% of the viewport
/** Explicit identity end keyframe: "none" does not reliably interpolate as identity. */
const IDENTITY = "translateY(0px) scale(1)";

function clear(elements: Iterable<HTMLElement>) {
  for (const element of elements) {
    element.style.removeProperty("opacity");
    element.style.removeProperty("transform");
    element.style.removeProperty("filter");
    element.style.removeProperty("will-change");
  }
}

function finish(target: HTMLElement, animated: HTMLElement[]) {
  target.setAttribute("data-revealed", "");
  target.removeAttribute("data-state");
  // Motion commits its final inline values right after `finished` resolves, so clear
  // two frames later; by then data-revealed makes the CSS default the final state.
  requestAnimationFrame(() => requestAnimationFrame(() => clear(animated)));
}

function fromTransform(variant: RevealVariant) {
  const { y, scale } = revealFrom[variant];
  const rise = variant === "card" && matchMedia(mq.mobile).matches ? cardRiseMobile : y;
  return `translateY(${rise}px) scale(${scale})`;
}

const EASE = `cubic-bezier(${easeEntrance.join(",")})`;

/** Weak GPUs (few cores, Safari's software blur paths) get a smaller blur radius, never none. */
function blurRadius() {
  if (matchMedia(mq.mobile).matches) return wordBlur.mobile;
  const safari = /^((?!chrome|android|crios|fxios|edg).)*safari/i.test(navigator.userAgent);
  const fewCores = (navigator.hardwareConcurrency ?? 8) <= 4;
  return safari || fewCores ? wordBlur.lowPower : wordBlur.desktop;
}

/**
 * The frosted word-by-word reveal: each word goes from blurred, faded and lowered to
 * crisp. One native (compositor) animation per word with all three properties in one
 * effect; opacity is in by `wordOpaqueAt` while blur keeps resolving, so words focus.
 * Layers are promoted only for the reveal. Long headings blur once at heading level.
 */
function revealHeading(heading: HTMLElement, running: Set<Animation>) {
  const words = [...heading.querySelectorAll<HTMLElement>(".sh-word")];
  const headingBlur = words.length > lineBlurAbove;
  // Promote the layers one frame before animating, so every effect can start on the compositor.
  for (const word of words) word.style.willChange = headingBlur ? "transform, opacity" : "transform, opacity, filter";
  if (headingBlur) heading.style.willChange = "filter";
  requestAnimationFrame(() => startHeading(heading, words, headingBlur, running));
}

function startHeading(heading: HTMLElement, words: HTMLElement[], headingBlur: boolean, running: Set<Animation>) {
  if (!heading.isConnected) return;
  const blur = blurRadius();
  heading.setAttribute("data-state", "revealing"); // drives the CSS veil sweep (one layer per heading)
  const animations = words.map((word) => {
    const order = Number(word.style.getPropertyValue("--i")) || 0;
    const from: Keyframe = { opacity: 0, transform: `translateY(${wordRise}px)` };
    const to: Keyframe = { opacity: 1, transform: "translateY(0px)" };
    if (!headingBlur) { from.filter = `blur(${blur}px)`; to.filter = "blur(0px)"; }
    return word.animate([{ ...from, offset: 0 }, { opacity: 1, offset: wordOpaqueAt }, { ...to, offset: 1 }], {
      duration: (word.hasAttribute("data-accent") ? duration.accentWord : duration.word) * 1000,
      delay: order * stagger.words * 1000,
      easing: EASE,
      fill: "both",
    });
  });
  if (headingBlur) {
    const last = (words.length - 1) * stagger.words + duration.accentWord;
    animations.push(heading.animate([{ filter: `blur(${blur}px)` }, { filter: "blur(0px)" }], { duration: last * 1000, easing: EASE, fill: "both" }));
  }
  animations.forEach((animation) => running.add(animation));
  Promise.all(animations.map((animation) => animation.finished))
    .then(() => {
      heading.setAttribute("data-revealed", "");
      heading.removeAttribute("data-state");
      // data-revealed makes the default CSS the final state; drop the animations and layers.
      animations.forEach((animation) => { animation.cancel(); running.delete(animation); });
      clear([...words, heading]);
    })
    .catch(() => { /* cancelled on unmount */ });
}

/** Hero/hub headings animate with CSS at first paint; release their layers when done. */
function releaseLoadHeadings() {
  const stops: (() => void)[] = [];
  for (const heading of document.querySelectorAll<HTMLElement>(".sh-load:not([data-revealed])")) {
    const words = [...heading.querySelectorAll<HTMLElement>(".sh-word")];
    const pending = new Set(words);
    const done = (event: AnimationEvent) => {
      pending.delete(event.target as HTMLElement);
      if (!pending.size) heading.setAttribute("data-revealed", "");
    };
    heading.addEventListener("animationend", done);
    stops.push(() => heading.removeEventListener("animationend", done));
  }
  return () => stops.forEach((stop) => stop());
}

/** Decorative infinite loops pause while their section is off-screen (no idle main-thread frames). */
function pauseOffscreenLoops() {
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) (entry.target as HTMLElement).toggleAttribute("data-offscreen", !entry.isIntersecting);
  });
  document.querySelectorAll("[data-loops]").forEach((element) => observer.observe(element));
  return () => observer.disconnect();
}

async function revealBlock(element: HTMLElement) {
  const variant = (element.getAttribute("data-reveal") || "up") as RevealVariant;
  const delay = parseFloat(element.style.getPropertyValue("--d")) / 1000 || 0;
  element.style.willChange = "transform, opacity";
  await animate(
    element,
    { opacity: [0, 1], transform: [fromTransform(variant), IDENTITY] },
    {
      duration: variant === "fade" ? duration.state * 1.6 : variant === "card" ? duration.card : duration.entrance,
      delay,
      ease: easeEntrance,
    },
  ).finished;
  finish(element, [element]);
}

/**
 * A card grid: cards land one after another (left to right), then each card's inner
 * parts (code lines, diff rows, evidence rows) follow in a softer second pass.
 */
async function revealGroup(group: HTMLElement) {
  const variant = (group.getAttribute("data-reveal-stagger") || "up") as RevealVariant;
  const isCard = variant === "card";
  const base = parseFloat(group.style.getPropertyValue("--d")) / 1000 || 0;
  const gap = isCard && matchMedia(mq.mobile).matches ? stagger.cardsMobile : stagger.cards;
  const items = [...group.querySelectorAll<HTMLElement>("[data-reveal-item]")];
  const animated: HTMLElement[] = [];
  const runs: Promise<unknown>[] = [];

  items.forEach((item, index) => {
    const itemDelay = base + index * gap;
    item.style.willChange = "transform, opacity";
    animated.push(item);
    runs.push(
      animate(
        item,
        { opacity: [0, 1], transform: [fromTransform(variant), IDENTITY] },
        { duration: isCard ? duration.card : duration.entrance, delay: itemDelay, ease: easeEntrance },
      ).finished,
    );
    item.querySelectorAll<HTMLElement>("[data-reveal-inner]").forEach((inner, innerIndex) => {
      animated.push(inner);
      runs.push(
        animate(
          inner,
          { opacity: [0, 1], transform: ["translateY(8px)", IDENTITY] },
          {
            duration: duration.cardInner,
            delay: itemDelay + duration.cardInnerDelay + innerIndex * stagger.inner,
            ease: easeEntrance,
          },
        ).finished,
      );
    });
  });

  await Promise.all(runs);
  finish(group, animated);
}

/** Reduced motion: card grids get a quick opacity fade only; everything else is instant. */
async function fadeIn(target: HTMLElement) {
  const parts = target.hasAttribute("data-reveal-stagger")
    ? [...target.querySelectorAll<HTMLElement>("[data-reveal-item]")]
    : [target];
  await Promise.all(parts.map((part) => animate(part, { opacity: [0, 1] }, { duration: duration.reducedFade }).finished));
  finish(target, parts);
}

const isCardTarget = (element: HTMLElement) =>
  element.getAttribute("data-reveal-stagger") === "card" || element.getAttribute("data-reveal") === "card";

/**
 * Desktop only: a card's inner visual drifts by at most `parallax.range` px with scroll
 * progress, easing toward it over ~`parallax.scrub`s. The card frame itself never moves.
 * The catch-up loop only runs while the scroll position is changing.
 */
function startParallax(): () => void {
  if (!matchMedia(mq.parallax).matches) return () => {};
  const stops: (() => void)[] = [];
  for (const element of document.querySelectorAll<HTMLElement>("[data-parallax]")) {
    const frame = element.parentElement ?? element;
    let target = 0;
    let current = 0;
    let raf = 0;
    let last = 0;
    const tick = (now: number) => {
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
      last = now;
      // Exponential catch-up: most of the way to the target within the scrub time.
      current += (target - current) * (1 - Math.exp((-dt * 4) / parallax.scrub));
      element.style.transform = `translate3d(0, ${current.toFixed(2)}px, 0)`;
      raf = Math.abs(target - current) > 0.05 ? requestAnimationFrame(tick) : 0;
    };
    const stopScroll = scroll(
      (progress: number) => {
        target = (0.5 - progress) * 2 * parallax.range;
        if (!raf) {
          last = 0;
          raf = requestAnimationFrame(tick);
        }
      },
      { target: frame, offset: ["start end", "end start"] },
    );
    stops.push(() => {
      stopScroll();
      cancelAnimationFrame(raf);
      element.style.removeProperty("transform");
    });
  }
  return () => stops.forEach((stop) => stop());
}

export function MotionRuntime() {
  useEffect(() => {
    const targets = [...document.querySelectorAll<HTMLElement>(TARGETS)].filter(
      (element) => !element.hasAttribute("data-revealed"),
    );
    const reduced = matchMedia(mq.reduced).matches;

    // Reduced motion: final states right away, except card grids, which fade in quickly on view.
    if (reduced) {
      targets.filter((element) => !isCardTarget(element)).forEach((element) => element.setAttribute("data-revealed", ""));
    }

    let cancelled = false;
    const running = new Set<Animation>();
    const stopLoad = releaseLoadHeadings();
    const stopLoops = pauseOffscreenLoops();
    const stops = targets
      .filter((element) => !reduced || isCardTarget(element))
      .map((element) => {
        const isHeading = element.hasAttribute("data-split");
        const margin = isHeading ? HEADING_TRIGGER : isCardTarget(element) ? cardTrigger : "0px 0px -10% 0px";
        const stop = inView(
          element,
          () => {
            stop();
            // Wait for web fonts so text never reflows mid-animation.
            document.fonts.ready.then(() => {
              if (cancelled) return;
              if (reduced) fadeIn(element);
              else if (isHeading) revealHeading(element, running);
              else if (element.hasAttribute("data-reveal-stagger")) revealGroup(element);
              else revealBlock(element);
            });
          },
          { margin, amount: "some" },
        );
        return stop;
      });

    const stopParallax = startParallax();

    return () => {
      cancelled = true;
      stops.forEach((stop) => stop());
      running.forEach((animation) => animation.cancel());
      stopLoad();
      stopLoops();
      stopParallax();
    };
  }, []);

  return null;
}
