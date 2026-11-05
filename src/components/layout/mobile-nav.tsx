"use client";

import Link from "next/link";
import { ChevronDown, Menu, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useNavSignals } from "@/lib/learning/nav-signals";
import { LeaderboardLink } from "./leaderboard-link";
import { ProjectsLink } from "./projects-link";
import { lessonIcons, useLessonSection } from "./lessons-menu";
import { createCta, lessonLinks, navLinks } from "./nav-links";

/**
 * Phone menu: opens with a short fade and slide (CSS, reduced-motion safe), traps
 * focus between the toggle and the links while open, closes on Escape or an outside
 * tap, and returns focus to the toggle. Closed, the panel is inert and invisible.
 */
export function MobileNav() {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  // "Lessons" is an accordion inside the phone menu, with the same two items as the desktop menu.
  const [lessonsOpen, setLessonsOpen] = useState(false);
  const lessonsId = useId();
  const current = useLessonSection();
  const { myLessons } = useNavSignals();

  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector<HTMLElement>("a, button")?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
        return;
      }
      if (event.key !== "Tab") return;
      // Focus trap: toggle button + menu links
      const focusable = [buttonRef.current, ...(panelRef.current?.querySelectorAll<HTMLElement>("a, button:not([disabled])") ?? [])].filter(
        Boolean,
      ) as HTMLElement[];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    function onPointer(event: PointerEvent) {
      const target = event.target as Node;
      if (!panelRef.current?.contains(target) && !buttonRef.current?.contains(target)) {
        setOpen(false);
      }
    }
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <div className="lg:hidden">
      <button
        ref={buttonRef}
        type="button"
        aria-expanded={open}
        aria-controls="mobile-menu"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex size-11 items-center justify-center rounded-xl text-foreground transition-colors duration-[180ms] hover:bg-foreground/5"
      >
        <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
        {open ? (
          <X aria-hidden="true" className="size-5" strokeWidth={1.8} />
        ) : (
          <Menu aria-hidden="true" className="size-5" strokeWidth={1.8} />
        )}
      </button>

      <div
        id="mobile-menu"
        ref={panelRef}
        data-open={open ? "" : undefined}
        inert={!open}
        className="mobile-menu absolute inset-x-0 top-[calc(100%+8px)] rounded-[14px] border border-border bg-surface p-2 shadow-[var(--shadow-float)]"
      >
        <ul>
          {navLinks.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                onClick={() => setOpen(false)}
                className="flex min-h-12 items-center rounded-xl px-4 text-[1rem] font-medium tracking-[-0.01em] text-foreground transition-colors duration-[180ms] hover:bg-surface-muted"
              >
                {link.label}
              </a>
            </li>
          ))}
          <li>
            <button
              type="button"
              aria-expanded={lessonsOpen}
              aria-controls={lessonsId}
              onClick={() => setLessonsOpen((value) => !value)}
              className="flex min-h-12 w-full items-center justify-between rounded-xl px-4 text-left text-[1rem] font-medium tracking-[-0.01em] text-foreground transition-colors duration-[180ms] hover:bg-surface-muted"
            >
              Lessons
              <ChevronDown aria-hidden="true" className="nav-chevron size-4" strokeWidth={2} />
            </button>
            <ul id={lessonsId} hidden={!lessonsOpen} className="pb-1 pl-3">
              {lessonLinks.map((link) => {
                const Icon = lessonIcons[link.id];
                return (
                  <li key={link.id}>
                    <Link href={link.href} onClick={() => setOpen(false)} aria-current={current === link.id ? "page" : undefined} className="nav-menu-item">
                      <span aria-hidden="true" className="nav-menu-icon"><Icon className="size-4" strokeWidth={1.8} /></span>
                      <span className="min-w-0">
                        <span className="flex items-center gap-2 font-medium text-foreground">
                          {link.label}
                          {link.id === "my" && myLessons !== null && <span className="library-count" aria-label={`${myLessons} ${myLessons === 1 ? "lesson" : "lessons"}`}>{myLessons}</span>}
                        </span>
                        <span className="mt-0.5 block text-[0.8125rem] leading-snug text-secondary">{link.description}</span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </li>
          <li><ProjectsLink mobile onNavigate={() => setOpen(false)} /></li>
          <li><LeaderboardLink mobile onNavigate={() => setOpen(false)} /></li>
          <li>
            <a
              href={createCta.href}
              onClick={() => setOpen(false)}
              className="flex min-h-12 items-center rounded-xl px-4 text-[1rem] font-medium tracking-[-0.01em] text-foreground transition-colors duration-[180ms] hover:bg-surface-muted"
            >
              {createCta.label}
            </a>
          </li>
        </ul>
      </div>
    </div>
  );
}
