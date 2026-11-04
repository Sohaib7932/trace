/**
 * Every link points somewhere real. Section links include the "/" path so they also
 * work from other pages (on the homepage they only scroll). "Lessons" is a small menu
 * (see lessons-menu.tsx); demo-only pages such as /today are not in the navbar.
 */
export const navLinks = [
  { href: "/#features", label: "Product" },
  { href: "/#how-it-works", label: "How it works" },
  { href: "/#progress", label: "Learning approach" },
] as const;

export type LessonSection = "trace" | "my";

export const lessonLinks = [
  { id: "trace", href: "/learn", label: "Trace lessons", description: "Short lessons on real code, checked on a server" },
  { id: "my", href: "/learn/my", label: "My lessons", description: "Lessons you asked Trace to make for you" },
] as const satisfies readonly { id: LessonSection; href: string; label: string; description: string }[];

/** Which part of Lessons a path belongs to, for highlighting the navbar and the switcher. */
export function lessonSection(pathname: string): LessonSection | null {
  if (/^\/learn\/(?:my|new|custom|requests|guides)(?:\/|$)/.test(pathname)) return "my";
  if (pathname === "/learn" || pathname.startsWith("/learn/")) return "trace";
  return null;
}

export const primaryCta = { href: "/learn", label: "Try Trace" } as const;

/** Primary action on the learning pages (lessons, today, account). */
export const createCta = { href: "/learn/new", label: "Create a lesson" } as const;
