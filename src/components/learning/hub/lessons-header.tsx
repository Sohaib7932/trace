"use client";

import Link from "next/link";
import { useLayoutEffect, useRef, type CSSProperties } from "react";
import { lessonLinks, type LessonSection } from "@/components/layout/nav-links";

const LAST = "trace.lessons.switcher";

/**
 * Shared header for /learn and /learn/my: a small pill, one heading, one short line, an
 * optional progress chip, and the "Trace lessons | My lessons" switcher.
 */
export function LessonsHeader({ current, heading, line, chip, hint }: {
  current: LessonSection;
  heading: React.ReactNode;
  line: string;
  chip?: React.ReactNode;
  hint?: string | null;
}) {
  return (
    <header className="pt-[clamp(40px,6vw,88px)] pb-[clamp(24px,3vw,36px)]">
      <p className="enter inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-[0.75rem] font-medium text-secondary shadow-[0_1px_2px_rgba(21,25,35,0.04)]">
        <span aria-hidden="true" className="size-2 rounded-[3px] bg-primary" />
        Lessons
      </p>
      <div className="mt-5 flex flex-wrap items-end gap-x-4 gap-y-3">
        {heading}
        {chip}
      </div>
      <p className="enter mt-3 max-w-[34rem] text-[1rem] leading-relaxed text-secondary sm:text-[1.0625rem]" style={{ "--d": "260ms" } as CSSProperties}>{line}</p>
      {hint && <p className="enter mt-2 text-[0.875rem] text-secondary" style={{ "--d": "300ms" } as CSSProperties}>{hint}</p>}
      <LessonsSwitcher current={current} />
    </header>
  );
}

/**
 * Two links with a sliding indicator. The indicator starts where the previous page left it
 * (remembered for this tab) and slides to the current page; reduced motion shows it in place.
 */
export function LessonsSwitcher({ current }: { current: LessonSection }) {
  const track = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    let previous: string | null = null;
    try { previous = sessionStorage.getItem(LAST); sessionStorage.setItem(LAST, current); } catch { /* storage blocked: no slide */ }
    const element = track.current;
    if (!element || (previous !== "trace" && previous !== "my") || previous === current) return;
    // Paint the indicator at the previous page's position once, then let CSS slide it home.
    element.dataset.at = previous;
    void element.offsetWidth;
    const frame = requestAnimationFrame(() => { element.dataset.at = current; });
    return () => { cancelAnimationFrame(frame); element.dataset.at = current; };
  }, [current]);

  return (
    <nav aria-label="Lesson library" className="enter mt-6" style={{ "--d": "340ms" } as CSSProperties}>
      <div ref={track} className="switcher" data-at={current}>
        <span aria-hidden="true" className="switcher-indicator" />
        <ul className="switcher-list">
          {lessonLinks.map((link) => (
            <li key={link.id}>
              <Link href={link.href} aria-current={current === link.id ? "page" : undefined} className="switcher-link">{link.label}</Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}
