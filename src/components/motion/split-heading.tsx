import type { CSSProperties, ElementType, ReactNode } from "react";

/**
 * A heading split into words for the word-by-word reveal (CLAUDE.md §7).
 *
 * Server-rendered: the final, readable text is the default CSS state. The hidden
 * "from" state only applies under html.js with motion allowed, and the motion
 * runtime (or CSS keyframes in load mode) resolves it.
 *
 * Accessibility: the full heading is in a visually hidden span; the animated word
 * spans are aria-hidden, so the heading is announced once, as a whole.
 */

export type HeadingSegment = string | { accent: string } | { br: true };

type Run = { text: string; accent: boolean };
type Word = { runs: Run[]; accent: boolean; order: number };

function toLines(segments: HeadingSegment[]): Word[][] {
  const lines: Word[][] = [[]];
  let current: Run[] = [];
  const flush = () => {
    if (current.length) {
      lines[lines.length - 1].push({
        runs: current,
        accent: current.some((run) => run.accent),
        order: 0,
      });
    }
    current = [];
  };
  for (const segment of segments) {
    if (typeof segment === "object" && "br" in segment) {
      flush();
      lines.push([]);
      continue;
    }
    const accent = typeof segment === "object";
    const text = typeof segment === "object" ? segment.accent : segment;
    // Split on ordinary spaces only; a no-break space keeps words together ("with AI.").
    text.split(/( )/).forEach((part) => {
      if (part === " ") flush();
      else if (part) current.push({ text: part, accent });
    });
  }
  flush();
  return lines;
}

/** Within each line, ordinary words reveal first and the accent word last. */
function assignOrder(lines: Word[][]) {
  let order = 0;
  for (const line of lines) {
    for (const word of line) if (!word.accent) word.order = order++;
    for (const word of line) if (word.accent) word.order = order++;
  }
  return order;
}

export function headingText(segments: HeadingSegment[]) {
  return segments
    .map((segment) => (typeof segment === "string" ? segment : "accent" in segment ? segment.accent : " "))
    .join("")
    .replace(/ /g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function SplitHeading({
  as: Tag = "h2",
  segments,
  id,
  className = "",
  mode = "view",
  accentClassName = "text-primary-display",
  tone = "light",
  baseDelay = 0,
  breakClassName = "hidden sm:block",
}: {
  as?: ElementType;
  segments: HeadingSegment[];
  id?: string;
  className?: string;
  /** "view": revealed by the motion runtime on scroll. "load": CSS keyframes at first paint. */
  mode?: "view" | "load";
  accentClassName?: string;
  tone?: "light" | "dark";
  /** Load mode only: delay before the first word, in ms. */
  baseDelay?: number;
  breakClassName?: string;
}) {
  const lines = toLines(segments);
  const count = assignOrder(lines);
  const label = headingText(segments);

  const content: ReactNode[] = [];
  lines.forEach((line, lineIndex) => {
    if (lineIndex > 0) content.push(<br key={`br-${lineIndex}`} className={breakClassName} />);
    line.forEach((word, wordIndex) => {
      if (lineIndex > 0 || wordIndex > 0) content.push(" ");
      content.push(
        <span
          key={`${lineIndex}-${wordIndex}`}
          className="sh-word"
          data-accent={word.accent ? "" : undefined}
          style={{ "--i": word.order } as CSSProperties}
        >
          {word.runs.map((run, runIndex) =>
            run.accent ? (
              <span key={runIndex} className={accentClassName}>
                {run.text}
              </span>
            ) : (
              <span key={runIndex}>{run.text}</span>
            ),
          )}
        </span>,
      );
    });
  });

  return (
    <Tag
      id={id}
      className={`sh ${mode === "load" ? "sh-load" : ""} ${tone === "dark" ? "sh-dark" : ""} ${className}`}
      data-split={mode === "view" ? "" : undefined}
      data-words={count}
      style={{ "--sh-base": `${baseDelay}ms` } as CSSProperties}
    >
      <span className="sr-only">{label}</span>
      <span aria-hidden="true">{content}</span>
    </Tag>
  );
}
