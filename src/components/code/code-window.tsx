import type { ReactNode } from "react";
import { CodeLens, type LensTarget } from "./code-lens";
import { CodeLines } from "./code-lines";
import { LensCaption } from "./lens-caption";

/**
 * macOS-style code window used for every code excerpt on the marketing site.
 * Server-rendered. With `magnify`, a client magnifier glides between target lines;
 * the first target is highlighted in the server HTML, so the static state works
 * without JavaScript and with reduced motion.
 */
export function CodeWindow({
  file,
  lang = "Python",
  meta,
  lines,
  start = 1,
  highlight = [],
  added = [],
  removed = [],
  tone = "light",
  size = "md",
  plain = false,
  magnify,
  lensSize = 140,
  className = "",
  label,
}: {
  file: string;
  lang?: string;
  /** Extra right-side label, e.g. "agent-generated · under review". */
  meta?: ReactNode;
  lines: string[];
  start?: number;
  highlight?: number[];
  added?: number[];
  removed?: number[];
  tone?: "light" | "dark";
  /** sm: 13px everywhere; md: 13px, 14px from 1280px. */
  size?: "sm" | "md";
  plain?: boolean;
  magnify?: LensTarget[];
  lensSize?: number;
  className?: string;
  /** Accessible name for the code region; defaults to the file name. */
  label?: string;
}) {
  const dark = tone === "dark";
  const staticHighlight = magnify?.length ? [...highlight, magnify[0].line] : highlight;
  const code = (
    <CodeLines
      lines={lines}
      start={start}
      highlight={staticHighlight}
      added={added}
      removed={removed}
      tone={tone}
      plain={plain}
    />
  );

  return (
    <figure
      className={`code-window overflow-hidden rounded-[13px] border ${
        dark ? "border-editor-line bg-editor" : "border-border bg-surface"
      } shadow-[0_1px_2px_rgba(21,25,35,0.05),0_18px_40px_-24px_rgba(21,25,35,0.28)] ${className}`}
    >
      {/* Window chrome */}
      <figcaption
        className={`relative flex items-center gap-3 border-b px-3.5 py-2 ${
          dark ? "border-editor-line bg-editor-surface" : "border-border bg-surface"
        }`}
      >
        <span aria-hidden="true" className="flex shrink-0 gap-1.5">
          <span className="size-[9px] rounded-full bg-[#ff5f57]" />
          <span className="size-[9px] rounded-full bg-[#febc2e]" />
          <span className="size-[9px] rounded-full bg-[#28c840]" />
        </span>
        <span
          className={`min-w-0 flex-1 truncate text-center font-mono text-[0.6875rem] ${
            dark ? "text-editor-foreground" : "text-secondary"
          }`}
        >
          {file}
          {meta && <span className="hidden sm:inline"> · {meta}</span>}
        </span>
        <span
          className={`shrink-0 rounded-[5px] border px-1.5 py-px font-mono text-[0.625rem] tracking-[0.04em] uppercase ${
            dark ? "border-editor-line text-editor-muted" : "border-border text-secondary"
          }`}
        >
          {lang}
        </span>
      </figcaption>

      <div
        data-code-body
        role="group"
        aria-label={label ?? `Code: ${file}`}
        className={`relative ${magnify ? "lens-body" : "overflow-x-auto"} ${
          dark ? "" : "code-surface"
        } ${dark ? "" : "code-light"} code-block ${size === "sm" ? "code-sm" : ""} py-3.5`}
      >
        <pre data-code-base className="relative z-[1] min-w-max">
          {code}
        </pre>
        {magnify?.length ? <CodeLens targets={magnify} size={lensSize} copy={code} /> : null}
      </div>
      {magnify?.length ? <LensCaption targets={magnify} /> : null}
    </figure>
  );
}
