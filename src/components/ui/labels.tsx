import { Check, Circle, CircleAlert, Lightbulb, X } from "lucide-react";
import type { ReactNode } from "react";

/** Small mono eyebrow with hairline rules. */
export function Eyebrow({
  children,
  align = "start",
  tone = "light",
}: {
  children: ReactNode;
  align?: "start" | "center";
  tone?: "light" | "dark";
}) {
  const rule = tone === "dark" ? "bg-editor-muted/40" : "bg-foreground/20";
  const text = tone === "dark" ? "text-editor-muted" : "text-secondary";
  return (
    <p
      className={`type-label flex items-center gap-3 ${text} ${
        align === "center" ? "justify-center" : ""
      }`}
    >
      <span aria-hidden="true" className={`h-px w-6 ${rule}`} />
      {children}
      {align === "center" && (
        <span aria-hidden="true" className={`h-px w-6 ${rule}`} />
      )}
    </p>
  );
}

/**
 * Marks content as sample data. Trace has no live backend yet, so every
 * result on the marketing page carries this label.
 */
export function SampleTag({
  children = "Sample output",
  tone = "light",
}: {
  children?: ReactNode;
  tone?: "light" | "dark";
}) {
  const styles =
    tone === "dark"
      ? "border-editor-line text-editor-muted"
      : "border-border-strong bg-surface text-secondary";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[0.6875rem] leading-none tracking-[0.04em] uppercase ${styles}`}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full border border-current" />
      {children}
    </span>
  );
}

type Status = "match" | "differs" | "pass" | "fail" | "hint" | "neutral";

const statusStyles: Record<Status, string> = {
  match: "bg-success-soft text-success",
  pass: "bg-success-soft text-success",
  differs: "bg-error-soft text-error",
  fail: "bg-error-soft text-error",
  hint: "bg-warning-soft text-warning",
  neutral: "bg-surface-muted text-secondary",
};

const statusIcons: Record<Status, typeof Check> = {
  match: Check,
  pass: Check,
  differs: X,
  fail: X,
  hint: Lightbulb,
  neutral: Circle,
};

/** Status always carries an icon and a word, never colour alone. */
export function StatusBadge({ status, children }: { status: Status; children: ReactNode }) {
  const Icon = statusIcons[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[0.75rem] leading-5 font-medium whitespace-nowrap ${statusStyles[status]}`}
    >
      <Icon aria-hidden="true" className="size-3.5" strokeWidth={2.2} />
      {children}
    </span>
  );
}

export function Note({ children }: { children: ReactNode }) {
  return (
    <p className="flex gap-2 text-[0.8125rem] leading-5 text-secondary">
      <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.8} />
      <span>{children}</span>
    </p>
  );
}
