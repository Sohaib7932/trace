import { CodeText } from "./code-line";

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
}: {
  lines: string[];
  start?: number;
  highlight?: number[];
  added?: number[];
  removed?: number[];
  tone?: "light" | "dark";
  /** Plain text (HTTP, JSON): no Python highlighting. */
  plain?: boolean;
}) {
  const dark = tone === "dark";
  return (
    <code className="block">
      {lines.map((line, index) => {
        const number = start + index;
        const isAdded = added.includes(number);
        const isRemoved = removed.includes(number);
        const isActive = highlight.includes(number);
        const rowTone = isAdded
          ? dark
            ? "bg-[rgba(110,200,150,0.12)]"
            : "bg-success-soft"
          : isRemoved
            ? dark
              ? "bg-[rgba(240,130,120,0.12)]"
              : "bg-error-soft"
            : isActive
              ? dark
                ? "bg-white/[0.05]"
                : "bg-primary-soft/80"
              : "";
        const rail = isAdded ? "bg-success" : isRemoved ? "bg-error" : isActive ? "bg-primary" : "";
        return (
          <span
            key={number}
            data-line={number}
            data-hl={isActive ? "" : undefined}
            className={`code-row relative flex pr-6 ${rowTone}`}
          >
            {rail && <span aria-hidden="true" className={`code-rail absolute inset-y-0 left-0 w-[2px] ${rail}`} />}
            <span
              aria-hidden="true"
              className={`w-10 shrink-0 pr-3 text-right select-none ${dark ? "text-[#5d6475]" : "text-tertiary"}`}
            >
              {number}
            </span>
            <span
              aria-hidden="true"
              className={`w-4 shrink-0 select-none ${isAdded ? "text-success" : isRemoved ? "text-error" : ""}`}
            >
              {isAdded ? "+" : isRemoved ? "−" : ""}
            </span>
            {isAdded && <span className="sr-only">Added line: </span>}
            {isRemoved && <span className="sr-only">Removed line: </span>}
            <span data-code-text className="whitespace-pre">
              {plain ? <span className="tok-plain">{line || "​"}</span> : <CodeText source={line} />}
            </span>
          </span>
        );
      })}
    </code>
  );
}
