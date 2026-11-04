"use client";

import Link from "next/link";
import { BookOpen, ChevronDown, Sparkles } from "lucide-react";
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { useNavSignals } from "@/lib/learning/nav-signals";
import { lessonLinks, lessonSection, type LessonSection } from "./nav-links";

export const lessonIcons: Record<LessonSection, typeof BookOpen> = { trace: BookOpen, my: Sparkles };

// The path is read from the browser (no usePathname), so the navbar never needs a Suspense
// boundary on dynamic routes. Server markup has no current section.
function subscribePath(notify: () => void) {
  window.addEventListener("popstate", notify);
  return () => window.removeEventListener("popstate", notify);
}
export function useLessonSection(): LessonSection | null {
  return useSyncExternalStore(subscribePath, () => lessonSection(window.location.pathname), () => null);
}

/**
 * Desktop "Lessons" menu: a disclosure button with two links. Click, Enter or Space toggles;
 * ArrowDown opens and moves into the list; arrows, Home and End move between items; Escape,
 * an outside click, Tab out or following a link closes it and focus returns to the button.
 */
export function LessonsMenu() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const listId = useId();
  const leaveTimer = useRef<number | undefined>(undefined);
  // Opens when a mouse rests on the button or the menu; a short delay keeps it open while the
  // pointer crosses the gap. Touch and keyboard still use click, Enter and Space.
  function hover(event: React.PointerEvent, enter: boolean) {
    if (event.pointerType !== "mouse") return;
    window.clearTimeout(leaveTimer.current);
    if (enter) setOpen(true);
    else leaveTimer.current = window.setTimeout(() => setOpen(false), 180);
  }
  const current = useLessonSection();
  const { myLessons } = useNavSignals();

  const items = () => [...(panel.current?.querySelectorAll<HTMLAnchorElement>("a") ?? [])];
  function close(focusTrigger: boolean) {
    setOpen(false);
    if (focusTrigger) trigger.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      const target = event.target as Node;
      if (!panel.current?.contains(target) && !trigger.current?.contains(target)) setOpen(false);
    }
    function navigated() { setOpen(false); }
    document.addEventListener("pointerdown", outside);
    window.addEventListener("popstate", navigated);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("popstate", navigated);
    };
  }, [open]);

  function onTriggerKey(event: React.KeyboardEvent) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    setOpen(true);
    // The panel is always rendered (inert while closed), so its links exist to focus.
    requestAnimationFrame(() => { const all = items(); (event.key === "ArrowUp" ? all.at(-1) : all[0])?.focus(); });
  }
  function onPanelKey(event: React.KeyboardEvent) {
    const all = items();
    const index = all.indexOf(document.activeElement as HTMLAnchorElement);
    const moves: Record<string, number> = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: all.length - 1 };
    if (event.key === "Escape") { event.preventDefault(); close(true); return; }
    if (!(event.key in moves)) return;
    event.preventDefault();
    all[(moves[event.key] + all.length) % all.length]?.focus();
  }

  return (
    <div
      className="relative"
      onPointerEnter={(event) => hover(event, true)}
      onPointerLeave={(event) => hover(event, false)}
      onBlur={(event) => { if (open && !event.currentTarget.contains(event.relatedTarget as Node | null)) setOpen(false); }}
    >
      <button
        ref={trigger}
        type="button"
        aria-expanded={open}
        aria-controls={listId}
        data-current={current ? "" : undefined}
        onClick={(event) => setOpen((value) => (event.detail === 0 ? !value : (event.nativeEvent as PointerEvent).pointerType === "mouse" ? true : !value))}
        onKeyDown={onTriggerKey}
        className="nav-trigger inline-flex min-h-11 items-center gap-1 rounded-lg px-3 text-[0.875rem] font-medium tracking-[-0.01em] text-secondary transition-colors duration-150 hover:text-foreground"
      >
        Lessons
        <ChevronDown aria-hidden="true" className="nav-chevron size-3.5" strokeWidth={2} />
      </button>
      <div ref={panel} id={listId} data-open={open ? "" : undefined} inert={!open} onKeyDown={onPanelKey} className="nav-menu">
        <ul className="grid gap-0.5">
          {lessonLinks.map((link) => {
            const Icon = lessonIcons[link.id];
            return (
              <li key={link.id}>
                <Link href={link.href} onClick={() => close(false)} aria-current={current === link.id ? "page" : undefined} className="nav-menu-item">
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
      </div>
    </div>
  );
}
