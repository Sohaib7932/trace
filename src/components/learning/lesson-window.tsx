"use client";

import { Check, Lock } from "lucide-react";
import { motion } from "motion/react";
import { Children, type ReactNode, type Ref } from "react";
import { TraceMark } from "@/components/brand/trace-mark";

/**
 * The lesson window used by every real lesson (Trace lessons and AI-created ones). It is the same
 * window as the homepage demo: a title bar with the step rail, code on the left, one step at a
 * time on the right, and a plain-language note along the bottom.
 */

const ease = [0.2, 0.8, 0.2, 1] as const;
export const RAIL_STEPS = ["Read", "Predict", "Modify", "Verify", "Revisit"] as const;

export const darkButton =
  "inline-flex min-h-11 items-center justify-center gap-2.5 rounded-full bg-foreground px-5 text-[0.9375rem] font-medium text-white transition-[background-color,transform] duration-200 hover:bg-[#2a2f3b] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-45";
export const pillButton =
  "inline-flex min-h-11 items-center gap-2 rounded-full border border-border-strong px-4 text-[0.875rem] font-medium transition-colors hover:border-foreground/30 disabled:cursor-not-allowed disabled:opacity-45";

export function LessonWindow({ crumb, current, done, badge, code, footer, announcement, children }: {
  /** Lesson title (and challenge), shown after "Lessons /". */
  crumb: string;
  /** Index into RAIL_STEPS of the step being worked on. */
  current: number;
  /** The loop is finished: every step is ticked and Revisit is shown as next. */
  done: boolean;
  badge: ReactNode;
  code: ReactNode;
  footer?: ReactNode;
  announcement?: string;
  children: ReactNode;
}) {
  return (
    <div className="relative overflow-hidden rounded-[20px] border border-border bg-surface shadow-[var(--shadow-window)] sm:rounded-[24px]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-border px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-2.5">
          <TraceMark className="size-5 shrink-0 text-foreground" />
          <p className="truncate text-[0.8125rem] text-secondary">
            <span className="hidden sm:inline">Lessons / </span>
            <span className="font-medium text-foreground">{crumb}</span>
          </p>
        </div>
        <StepRail current={current} done={done} />
        <div className="ml-auto">{badge}</div>
      </div>

      <div className="grid lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <div className="code-surface code-light flex min-w-0 flex-col">{code}</div>
        <div className="relative flex min-w-0 flex-col border-t border-border lg:border-t-0 lg:border-l">
          <div className="flex-1 px-5 py-6 sm:px-7 sm:py-7">
            <motion.div key={current} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.26, ease }}>
              {children}
            </motion.div>
          </div>
        </div>
      </div>

      {footer && <p className="border-t border-border bg-surface-muted/60 px-5 py-2.5 text-[0.75rem] leading-5 text-secondary">{footer}</p>}
      <p aria-live="polite" className="sr-only">{announcement}</p>
    </div>
  );
}

export function StepRail({ current, done }: { current: number; done: boolean }) {
  return (
    <ol className="order-last flex w-full items-center gap-1 overflow-x-auto md:order-none md:w-auto" aria-label="Lesson steps">
      {RAIL_STEPS.map((label, index) => {
        const complete = index < current || (done && index === current);
        const active = index === current && !done;
        const next = done && index === current + 1;
        return (
          <li key={label} className="flex shrink-0 items-center gap-1">
            {index > 0 && <span aria-hidden="true" className={`h-px w-3 sm:w-4 ${index <= current ? "bg-foreground/40" : "bg-border-strong"}`} />}
            <span
              aria-current={active ? "step" : undefined}
              className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[0.75rem] font-medium transition-colors duration-300 ${active ? "bg-foreground text-white" : complete ? "text-foreground" : "text-secondary"}`}
            >
              {complete ? <Check aria-hidden="true" className="size-3" strokeWidth={2.4} /> : <span aria-hidden="true" className={`size-1.5 rounded-full ${active ? "bg-primary" : "border border-current"}`} />}
              <span className={active ? "" : "sr-only sm:not-sr-only"}>{label}</span>
              {complete && <span className="sr-only"> (done)</span>}
              {next && <span className="hidden text-secondary sm:inline"> · next</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function StepHeading({ headingRef, step, title }: { headingRef?: Ref<HTMLHeadingElement>; step: number; title: string }) {
  return (
    <div className="mb-4 flex items-baseline gap-3">
      <span className="font-mono text-[0.75rem] text-primary-ink">0{step}</span>
      <h3 ref={headingRef} tabIndex={-1} className="text-[1.125rem] font-semibold tracking-[-0.02em] outline-none">{title}</h3>
    </div>
  );
}

/** A choice with an optional mono chip (a status, a letter) and a short detail line. */
export function OptionCard({ name, selected, onSelect, chip, title, detail, disabled, tried }: {
  name: string; selected: boolean; onSelect: () => void; chip?: ReactNode; title: ReactNode; detail?: ReactNode; disabled?: boolean; tried?: boolean;
}) {
  return (
    <label className={`group flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 transition-[border-color,background-color,box-shadow] duration-200 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-foreground ${selected ? "border-foreground bg-surface shadow-[0_0_0_1px_var(--foreground)]" : "border-border bg-surface hover:border-border-strong hover:bg-surface-muted/60"} ${disabled ? "cursor-not-allowed opacity-60" : ""}`}>
      <input type="radio" name={name} checked={selected} onChange={onSelect} disabled={disabled} className="sr-only" />
      <span aria-hidden="true" className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border transition-colors ${selected ? "border-foreground" : "border-border-strong"}`}>
        <span className={`size-2 rounded-full bg-foreground transition-transform duration-200 ${selected ? "scale-100" : "scale-0"}`} />
      </span>
      <span className="min-w-0">
        <span className="flex items-start gap-2">
          {chip && <span className="shrink-0 rounded-md bg-surface-muted px-1.5 py-px font-mono text-[0.75rem] font-medium">{chip}</span>}
          <span className="min-w-0 text-[0.875rem] font-medium break-words">{title}{tried && <span className="ml-2 text-[0.8125rem] font-normal text-secondary">tried</span>}</span>
        </span>
        {detail && <span className="mt-0.5 block text-[0.8125rem] leading-5 text-secondary">{detail}</span>}
      </span>
    </label>
  );
}

export function LockedCard({ label = "Your prediction", children, note }: { label?: string; children: ReactNode; note?: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface-muted px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="type-label text-secondary">{label}</p>
          <p className="mt-1 text-[0.9375rem] font-medium break-words whitespace-pre-wrap">{children}</p>
        </div>
        <span className="inline-flex shrink-0 items-center gap-1.5 text-[0.75rem] font-medium text-secondary"><Lock aria-hidden="true" className="size-3.5" strokeWidth={2} />Locked</span>
      </div>
      {note && <p className="mt-1.5 text-[0.8125rem] leading-5 text-secondary">{note}</p>}
    </div>
  );
}

export function EvidenceCard({ title, tag, children }: { title: string; tag?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-surface px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="type-label text-secondary">{title}</h4>
        {tag && <span className="font-mono text-[0.625rem] tracking-[0.06em] text-secondary uppercase">{tag}</span>}
      </div>
      {children}
    </section>
  );
}

/** Children arrive one after another; false/empty children are skipped. */
export function Staggered({ children }: { children: ReactNode }) {
  const items = Children.toArray(children);
  return (
    <motion.div className="mt-5 grid gap-3" initial="hidden" animate="shown" variants={{ shown: { transition: { staggerChildren: 0.09 } } }}>
      {items.map((child, index) => (
        <motion.div key={index} variants={{ hidden: { opacity: 0, y: 8 }, shown: { opacity: 1, y: 0 } }} transition={{ duration: 0.32, ease }}>{child}</motion.div>
      ))}
    </motion.div>
  );
}

export function WhyList({ title = "Why it happened", lines }: { title?: string; lines: string[] }) {
  return (
    <div className="pt-2">
      <h4 className="type-label text-secondary">{title}</h4>
      <ol className="mt-3 space-y-2.5">
        {lines.map((line, index) => (
          <li key={index} className="flex gap-3 text-[0.875rem] leading-relaxed">
            <span aria-hidden="true" className="mt-[3px] font-mono text-[0.6875rem] text-primary-ink">0{index + 1}</span>
            <span className="whitespace-pre-wrap">{line}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function AttemptCard({ badges, children }: { badges: ReactNode; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface-muted px-4 py-3.5">
      <p className="type-label text-secondary">This attempt</p>
      <div className="mt-2.5 flex flex-wrap gap-1.5">{badges}</div>
      {children && <p className="mt-3 text-[0.8125rem] leading-5 text-secondary">{children}</p>}
    </div>
  );
}

export function HintNote({ index, children }: { index?: number; children: ReactNode }) {
  return (
    <p className="rounded-xl border border-warning/25 bg-warning-soft px-4 py-3 text-[0.875rem] leading-relaxed text-foreground">
      <span className="font-medium text-warning">Hint{index ? ` ${index}` : ""} · </span>{children}
    </p>
  );
}

export function NotYet({ children }: { children: ReactNode }) {
  return (
    <p className="rounded-xl border border-error/20 bg-error-soft px-4 py-3 text-[0.875rem] leading-relaxed text-foreground">
      <span className="font-medium text-error">Not yet · </span>{children}
    </p>
  );
}
