import type { ReactNode } from "react";

/** Section intro: small pill label, left-aligned large heading, one muted line of subtext. */
export function SectionHeading({
  id,
  eyebrow,
  title,
  children,
  tone = "light",
}: {
  id: string;
  eyebrow: string;
  title: ReactNode;
  children?: ReactNode;
  tone?: "light" | "dark";
}) {
  const dark = tone === "dark";
  return (
    <div data-reveal className="max-w-[44rem]">
      <p
        className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[0.75rem] font-medium ${
          dark
            ? "border-editor-line bg-editor-surface text-editor-muted"
            : "border-border bg-surface text-secondary shadow-[0_1px_2px_rgba(21,25,35,0.04)]"
        }`}
      >
        <span aria-hidden="true" className="size-2 rounded-[3px] bg-primary" />
        {eyebrow}
      </p>
      <h2 id={id} className={`type-h2 mt-5 ${dark ? "text-editor-foreground" : "text-foreground"}`}>
        {title}
      </h2>
      {children && (
        <p className={`mt-4 text-[1rem] leading-relaxed ${dark ? "text-editor-muted" : "text-secondary"}`}>
          {children}
        </p>
      )}
    </div>
  );
}
