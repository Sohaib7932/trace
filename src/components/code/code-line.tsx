import { tokenizePython } from "./highlight";

/** Renders one highlighted Python line. Works in Server and Client Components. */
export function CodeText({ source }: { source: string }) {
  if (source === "") return <>{"​"}</>;
  return (
    <>
      {tokenizePython(source).map((token, index) => (
        <span key={index} className={`tok-${token.kind}`}>
          {token.text}
        </span>
      ))}
    </>
  );
}

/**
 * A static code excerpt with line numbers. `start` sets the first line number,
 * `highlight` marks lines (by their displayed number) with an active-line rail.
 */
export function CodeExcerpt({
  lines,
  start = 1,
  highlight = [],
  added = [],
  removed = [],
  tone = "dark",
  label,
}: {
  lines: string[];
  start?: number;
  highlight?: number[];
  added?: number[];
  removed?: number[];
  tone?: "dark" | "light";
  label?: string;
}) {
  const dark = tone === "dark";
  return (
    <div
      role="group"
      aria-label={label}
      className={`code-block overflow-x-auto py-3 ${dark ? "bg-editor" : "code-light"}`}
    >
      <pre className="min-w-max">
        <code className="block">
          {lines.map((line, index) => {
            const number = start + index;
            const isAdded = added.includes(number);
            const isRemoved = removed.includes(number);
            const isActive = highlight.includes(number);
            const marker = isAdded ? "+" : isRemoved ? "−" : " ";
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
                    ? "bg-white/[0.045]"
                    : "bg-primary-soft/70"
                  : "";
            const rail = isActive || isAdded || isRemoved;
            return (
              <span key={number} className={`relative flex pr-5 ${rowTone}`}>
                {rail && (
                  <span
                    aria-hidden="true"
                    className={`absolute inset-y-0 left-0 w-[2px] ${
                      isAdded ? "bg-success" : isRemoved ? "bg-error" : "bg-primary"
                    }`}
                  />
                )}
                <span
                  aria-hidden="true"
                  className={`w-10 shrink-0 pr-2 text-right select-none ${
                    dark ? "text-[#5d6475]" : "text-tertiary"
                  }`}
                >
                  {number}
                </span>
                <span
                  aria-hidden="true"
                  className={`w-5 shrink-0 text-center select-none ${
                    isAdded ? "text-success" : isRemoved ? "text-error" : ""
                  } ${dark && isAdded ? "!text-[#7fd1a4]" : ""} ${dark && isRemoved ? "!text-[#f08c84]" : ""}`}
                >
                  {marker}
                </span>
                {isAdded && <span className="sr-only">Added line: </span>}
                {isRemoved && <span className="sr-only">Removed line: </span>}
                <span className="whitespace-pre">
                  <CodeText source={line} />
                </span>
              </span>
            );
          })}
        </code>
      </pre>
    </div>
  );
}
