"use client";

import { Info } from "lucide-react";
import { useId, useState } from "react";
import { aiMode } from "@/lib/ai/client";

/**
 * Persistent label on every surface a mock drives. The tooltip opens on hover and on
 * keyboard focus (and stays readable via aria-describedby for screen readers).
 */
export function DemoLabel({ className = "", text = "Demo responses" }: { className?: string; text?: string }) {
  const tip = useId();
  const [open, setOpen] = useState(false);
  if (aiMode() !== "mock") return null;
  return (
    <span className={`relative inline-flex ${className}`}>
      <button
        type="button"
        aria-describedby={tip}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}
        className="demo-label inline-flex min-h-7 items-center gap-1 rounded-full border border-warning/40 bg-warning-soft px-2.5 text-[0.75rem] font-medium text-warning"
      >
        <Info aria-hidden="true" className="size-3.5" strokeWidth={2} />
        {text}
      </button>
      <span
        id={tip}
        role="tooltip"
        className={`pointer-events-none absolute top-[calc(100%+6px)] right-0 z-10 w-56 rounded-lg bg-foreground px-3 py-2 text-[0.75rem] leading-snug text-white shadow-[var(--shadow-float)] transition-opacity duration-150 ${open ? "opacity-100" : "opacity-0"}`}
      >
        Scripted while the AI backend is being connected. Not real AI and not real verification.
      </span>
    </span>
  );
}
