"use client";

import { animate, inView } from "motion";
import { useEffect } from "react";
import {
  duration,
  easeEntrance,
  mq,
  revealFrom,
  stagger,
  wordBlur,
  wordRise,
  type RevealVariant,
} from "@/lib/motion/tokens";

/**
 * One small client runtime for every scroll reveal on the page.
 *
 * Server Components mark content with <Reveal> / <SplitHeading>. CSS hides it only
 * under html.js with motion allowed; this runtime animates it in once (Motion's
 * inView + animate), then sets data-revealed and removes every inline style, so the
 * final DOM is exactly the default CSS state.
 */

const TARGETS = "[data-reveal], [data-reveal-stagger], [data-split]";
const HEADING_TRIGGER = "0px 0px -15% 0px"; // fires at ~85% of the viewport

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

/** Explicit identity end keyframe: "none" does not reliably interpolate as identity. */
const IDENTITY = "translateY(0px) scale(1)";

function fromTransform(variant: RevealVariant) {
  const { y, scale } = revealFrom[variant];
  return `translateY(${y}px) scale(${scale})`;
}

async function revealHeading(heading: HTMLElement) {
  const words = [...heading.querySelectorAll<HTMLElement>(".sh-word")];
  const blur = matchMedia(mq.mobile).matches ? wordBlur.mobile : wordBlur.desktop;
  heading.setAttribute("data-state", "revealing"); // drives the CSS veil sweep
  await Promise.all(
    words.map((word) => {
      word.style.willChange = "transform, opacity, filter";
      const order = Number(word.style.getPropertyValue("--i")) || 0;
      return animate(
        word,
        {
          opacity: [0, 1],
          filter: [`blur(${blur}px)`, "blur(0px)"],
          transform: [`translateY(${wordRise}px)`, "translateY(0px)"],
        },
        {
          duration: word.hasAttribute("data-accent") ? duration.accentWord : duration.word,
          delay: order * stagger.words,
          ease: easeEntrance,
        },
      ).finished;
    }),
  );
  finish(heading, words);
}

async function revealBlock(element: HTMLElement) {
  const variant = (element.getAttribute("data-reveal") ?? "up") as RevealVariant;
  const delay = parseFloat(element.style.getPropertyValue("--d")) / 1000 || 0;
  element.style.willChange = "transform, opacity";
  await animate(
    element,
    { opacity: [0, 1], transform: [fromTransform(variant), IDENTITY] },
    { duration: variant === "fade" ? duration.state * 1.6 : duration.entrance, delay, ease: easeEntrance },
  ).finished;
  finish(element, [element]);
}

async function revealGroup(group: HTMLElement) {
  const variant = (group.getAttribute("data-reveal-stagger") ?? "up") as RevealVariant;
  const base = parseFloat(group.style.getPropertyValue("--d")) / 1000 || 0;
  const items = [...group.querySelectorAll<HTMLElement>("[data-reveal-item]")];
  const animated: HTMLElement[] = [];
  const runs: Promise<unknown>[] = [];

  items.forEach((item, index) => {
    const itemDelay = base + index * stagger.cards;
    item.style.willChange = "transform, opacity";
    animated.push(item);
    runs.push(
      animate(
        item,
        { opacity: [0, 1], transform: [fromTransform(variant), IDENTITY] },
        { duration: duration.entrance, delay: itemDelay, ease: easeEntrance },
      ).finished,
    );
    // Secondary reveal inside the item: diff lines, evidence rows and so on
    item.querySelectorAll<HTMLElement>("[data-reveal-inner]").forEach((inner, innerIndex) => {
      animated.push(inner);
      runs.push(
        animate(
          inner,
          { opacity: [0, 1], transform: ["translateY(8px)", IDENTITY] },
          {
            duration: duration.state * 1.4,
            delay: itemDelay + 0.22 + innerIndex * stagger.inner,
            ease: easeEntrance,
          },
        ).finished,
      );
    });
  });

  await Promise.all(runs);
  finish(group, animated);
}

export function MotionRuntime() {
  useEffect(() => {
    const targets = [...document.querySelectorAll<HTMLElement>(TARGETS)].filter(
      (element) => !element.hasAttribute("data-revealed"),
    );

    // Reduced motion: show final states immediately, no movement.
    if (matchMedia(mq.reduced).matches) {
      targets.forEach((element) => element.setAttribute("data-revealed", ""));
      return;
    }

    let cancelled = false;
    const stops = targets.map((element) => {
      const isHeading = element.hasAttribute("data-split");
      const stop = inView(
        element,
        () => {
          stop();
          // Wait for web fonts so word spans never reflow mid-animation.
          document.fonts.ready.then(() => {
            if (cancelled) return;
            if (isHeading) revealHeading(element);
            else if (element.hasAttribute("data-reveal-stagger")) revealGroup(element);
            else revealBlock(element);
          });
        },
        { margin: isHeading ? HEADING_TRIGGER : "0px 0px -10% 0px", amount: 0.1 },
      );
      return stop;
    });

    return () => {
      cancelled = true;
      stops.forEach((stop) => stop());
    };
  }, []);

  return null;
}
