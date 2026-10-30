"use client";

import { Menu, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { navLinks } from "./nav-links";

/**
 * Phone menu: opens with a short fade and slide (CSS, reduced-motion safe), traps
 * focus between the toggle and the links while open, closes on Escape or an outside
 * tap, and returns focus to the toggle. Closed, the panel is inert and invisible.
 */
export function MobileNav() {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    panelRef.current?.querySelector<HTMLElement>("a")?.focus();

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
        return;
      }
      if (event.key !== "Tab") return;
      // Focus trap: toggle button + menu links
      const focusable = [buttonRef.current, ...(panelRef.current?.querySelectorAll<HTMLElement>("a") ?? [])].filter(
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
    <div className="md:hidden">
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
        </ul>
      </div>
    </div>
  );
}
