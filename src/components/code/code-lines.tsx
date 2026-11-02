import type { CSSProperties, ReactNode } from "react";
import { CodeText } from "./code-line";

export type RowKind = "normal" | "active" | "added" | "removed";

/** Leading spaces of a source line (its indentation, in characters). */
export const indentOf = (line: string) => line.length - line.trimStart().length;

/**
 * One code row: rail, line number, diff marker, text. With `wrap`, long lines soft-wrap
 * with a hanging indent (continuation lines start under the line's own indentation plus
 * two characters), so the number gutter stays aligned and no horizontal scroll is needed.
 */
export function CodeRow({ number, kind = "normal", tone = "light", wrap = false, indent = 0, children, className = "", ...rest }: {
  number: number | null;
  kind?: RowKind;
  tone?: "light" | "dark";
  wrap?: boolean;
  /** Leading spaces of this line; used for the hanging indent when wrapping. */
  indent?: number;
  children: ReactNode;
  className?: string;
} & Partial<Record<`data-${string}`, string>>) {
  const dark = tone === "dark";
  const isAdded = kind === "added";
  const isRemoved = kind === "removed";
  const isActive = kind === "active";
  const rowTone = isAdded
    ? dark ? "bg-[rgba(110,200,150,0.12)]" : "bg-success-soft"
    : isRemoved
      ? dark ? "bg-[rgba(240,130,120,0.12)]" : "bg-error-soft"
      : isActive
        ? dark ? "bg-white/[0.05]" : "bg-primary-soft/80"
        : "";
  const rail = isAdded ? "bg-success" : isRemoved ? "bg-error" : isActive ? "bg-primary" : "";
  const hanging = indent + 2;
  return (
    <span {...rest} className={`code-row relative flex pr-4 ${rowTone} ${className}`}>
      {rail && <span aria-hidden="true" className={`code-rail absolute inset-y-0 left-0 w-[2px] ${rail}`} />}
      <span aria-hidden="true" className={`w-10 shrink-0 pr-3 text-right select-none ${dark ? "text-[#5d6475]" : "text-tertiary"}`}>
        {number ?? ""}
      </span>
      <span aria-hidden="true" className={`w-4 shrink-0 select-none ${isAdded ? "text-success" : isRemoved ? "text-error" : ""}`}>
        {isAdded ? "+" : isRemoved ? "−" : ""}
      </span>
      {isAdded && <span className="sr-only">Added line: </span>}
      {isRemoved && <span className="sr-only">Removed line: </span>}
      <span
        data-code-text
        className={wrap ? `code-wrap min-w-0 flex-1 ${isRemoved ? "line-through decoration-error/60" : ""}` : `whitespace-pre ${isRemoved ? "line-through decoration-error/60" : ""}`}
        style={wrap ? ({ paddingLeft: `${hanging}ch`, textIndent: `-${hanging}ch` } as CSSProperties) : undefined}
      >
        {children}
      </span>
    </span>
  );
}

/**
 * Code rows with line numbers and diff markers. Server-safe, and rendered twice
 * by the magnifier (base + 1.6x lens copy), so it must be deterministic.
 */
export function CodeLines({
  lines,
  start = 1,
  highlight = [],
  added = [],
  removed = [],
  tone = "light",
  plain = false,
  revealRows = false,
  wrap = false,
}: {
  lines: string[];
  start?: number;
  highlight?: number[];
  added?: number[];
  removed?: number[];
  tone?: "light" | "dark";
  /** Plain text (HTTP, JSON): no JavaScript highlighting. */
  plain?: boolean;
  /** Mark each row for a secondary reveal. */
  revealRows?: boolean;
  /** Soft-wrap long lines with a hanging indent instead of scrolling. */
  wrap?: boolean;
}) {
  return (
    <code className="block">
      {lines.map((line, index) => {
        const number = start + index;
        const kind: RowKind = added.includes(number) ? "added" : removed.includes(number) ? "removed" : highlight.includes(number) ? "active" : "normal";
        return (
          <CodeRow
            key={number}
            number={number}
            kind={kind}
            tone={tone}
            wrap={wrap}
            indent={indentOf(line)}
            data-line={String(number)}
            data-hl={kind === "active" ? "" : undefined}
            data-reveal-inner={revealRows ? "" : undefined}
          >
            {plain ? <span className="tok-plain">{line || "​"}</span> : <CodeText source={line} />}
          </CodeRow>
        );
      })}
    </code>
  );
}
