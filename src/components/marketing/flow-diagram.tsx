"use client";

import { Check, RotateCcw, X } from "lucide-react";
import { animate, inView } from "motion";
import { useEffect, useRef, type CSSProperties } from "react";
import { SampleTag } from "@/components/ui/labels";
import { duration, easeEntrance, mq, stagger } from "@/lib/motion/tokens";

export type FlowNode = {
  kicker: string;
  title: string;
  detail?: string;
  tone?: "neutral" | "success" | "error";
};
export type FlowBranch = { label: string; nodes: FlowNode[]; dim?: boolean; dimNote?: string };

/**
 * A request traced through code: a linear path that forks into two branches.
 * Server HTML is the final, fully drawn diagram (no JS, reduced motion). With motion
 * allowed it plays once on view: node rises, connector draws with a travelling dot,
 * next node scales in as the line arrives, branches 120ms apart, success check springs.
 */
export function FlowDiagram({
  title,
  path,
  branches,
  tone = "light",
}: {
  title: string;
  path: FlowNode[];
  branches: [FlowBranch, FlowBranch];
  tone?: "light" | "dark";
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const dark = tone === "dark";

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    if (matchMedia(mq.reduced).matches) {
      root.setAttribute("data-revealed", "");
      return;
    }
    const stop = inView(
      root,
      () => {
        stop();
        play(root);
      },
      { amount: 0.35 },
    );
    return () => stop();
  }, []);

  return (
    <figure
      ref={rootRef}
      data-flow
      className={`flow ${dark ? "flow-dark" : ""}`}
      style={{ "--flow-pairs": path.length - 1 } as CSSProperties}
      aria-label={`${title}: ${describe(path, branches)}`}
    >
      <figcaption className="mb-5 flex flex-wrap items-center gap-3">
        <span className={`type-label ${dark ? "text-editor-muted" : "text-secondary"}`}>{title}</span>
        <SampleTag tone={dark ? "dark" : "light"}>Sample run</SampleTag>
        <button
          type="button"
          onClick={() => rootRef.current && play(rootRef.current)}
          className={`flow-replay ml-auto min-h-9 items-center gap-1.5 rounded-lg px-2.5 text-[0.8125rem] font-medium transition-colors duration-[180ms] ${
            dark ? "text-editor-muted hover:text-editor-foreground" : "text-secondary hover:text-foreground"
          }`}
        >
          <RotateCcw aria-hidden="true" className="size-3.5" strokeWidth={2} />
          Replay
        </button>
      </figcaption>

      <div aria-hidden="true" className="flow-grid">
        {/* Linear path */}
        {path.map((node, index) => (
          <div key={node.title} className="contents">
            {index > 0 && <Connector />}
            <Node node={node} />
          </div>
        ))}

        {/* Fork (desktop): two arms from the last path node into the branch rows */}
        <div className="flow-fork">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full">
            <path data-flow-arm="0" className="flow-path" pathLength={1} d="M0 50 C 55 50, 45 25, 100 25" />
            <path data-flow-arm="1" className="flow-path" pathLength={1} d="M0 50 C 55 50, 45 75, 100 75" />
          </svg>
          {branches.map((branch, index) => (
            <span key={branch.label} className={`flow-fork-label ${index === 0 ? "top-[25%]" : "top-[75%]"}`}>
              {branch.label}
            </span>
          ))}
          <span data-flow-dot className="flow-dot" />
          <span data-flow-dot className="flow-dot" />
        </div>

        <div className="flow-branches">
          {branches.map((branch, branchIndex) => (
            <div key={branch.label} data-flow-branch={branchIndex} className={`flow-branch ${branch.dim ? "flow-dim" : ""}`}>
              <span className="flow-branch-arrow" />
              {/* Phones: label + connector stand in for the fork */}
              <p className="flow-branch-label-sm">
                If {branch.label}
              </p>
              <Connector mobileOnly />
              {branch.nodes.map((node, index) => (
                <div key={node.title} className="contents">
                  {index > 0 && <Connector />}
                  <Node node={node} dim={branch.dim} />
                </div>
              ))}
              {branch.dim && branch.dimNote && <p className="flow-dim-note">{branch.dimNote}</p>}
            </div>
          ))}
        </div>
      </div>
    </figure>
  );
}

function Node({ node, dim = false }: { node: FlowNode; dim?: boolean }) {
  const tone = node.tone ?? "neutral";
  const showCheck = tone === "success" && !dim;
  return (
    <div data-flow-node className={`flow-node flow-node-${tone}`}>
      <p className="flow-node-kicker">{node.kicker}</p>
      <p className="flow-node-title">
        {tone === "error" && <X aria-hidden="true" className="size-3.5 shrink-0 text-error" strokeWidth={2.4} />}
        <span>{node.title}</span>
      </p>
      {node.detail && <p className="flow-node-detail">{node.detail}</p>}
      {showCheck && (
        <span data-flow-check className="flow-check">
          <Check className="size-3" strokeWidth={3} />
        </span>
      )}
    </div>
  );
}

function Connector({ mobileOnly = false }: { mobileOnly?: boolean }) {
  return (
    <div data-flow-conn className={`flow-conn ${mobileOnly ? "flow-conn-sm" : ""}`}>
      {/* Straight 1.5px lines (not SVG): they draw by scaling on the compositor */}
      <span aria-hidden="true" className="flow-conn-h flow-line" />
      <span aria-hidden="true" className="flow-conn-v flow-line" />
      <span className="flow-arrow" />
      <span data-flow-dot className="flow-dot" />
    </div>
  );
}

function describe(path: FlowNode[], branches: FlowBranch[]) {
  const line = path.map((node) => node.title).join(", then ");
  const forks = branches
    .map((branch) => `if ${branch.label}: ${branch.nodes.map((node) => node.title).join(", then ")}${branch.dim ? " (not reached)" : ""}`)
    .join("; ");
  return `${line}; ${forks}.`;
}

/* ---------------------------------------------------------------------------------- */

const shown = (element: Element) => element.getClientRects().length > 0;

type Segment = [Element, Record<string, unknown>, Record<string, unknown>];

const EASE = `cubic-bezier(${easeEntrance.join(",")})`;

/**
 * Starts one segment. Everything is scheduled up front with a delay, so the compositor
 * runs the whole sequence; a JS-driven sequence starts each segment on the main thread,
 * which cost a dropped frame per start on phones. The spring check keeps Motion's spring.
 */
function start([element, keyframes, options]: Segment): Promise<unknown> {
  const at = Number(options.at ?? 0);
  if (options.type === "spring") {
    return animate(element, keyframes as never, { ...options, at: undefined, delay: at } as never).finished;
  }
  return (element as HTMLElement).animate(keyframes as PropertyIndexedKeyframes, {
    delay: at * 1000,
    duration: Number(options.duration ?? 0.3) * 1000,
    easing: options.ease ? EASE : "linear",
    fill: "both",
  }).finished;
}

/** Builds and plays the whole sequence, then cleans up. */
async function play(root: HTMLElement) {
  if (matchMedia(mq.reduced).matches) return;
  root.removeAttribute("data-revealed");
  // Horizontal when the diagram itself is wide enough (container query in globals.css)
  const desktop = getComputedStyle(root.querySelector(".flow-grid")!).display === "grid";
  const segments: Segment[] = [];
  const animated: HTMLElement[] = [];
  const add = (element: Element | null | undefined, keyframes: Record<string, unknown>, options: Record<string, unknown>) => {
    if (!element) return;
    segments.push([element, keyframes, options]);
    animated.push(element as HTMLElement);
  };

  const nodeIn = (node: Element, at: number) =>
    // Explicit identity end keyframe: inside a sequence, "none" does not interpolate as identity.
    add(node, { opacity: [0, 1], transform: ["translateY(12px) scale(0.96)", "translateY(0px) scale(1)"] }, { at, duration: duration.entrance * 0.77, ease: easeEntrance });

  const connector = (conn: Element, at: number) => {
    // Straight line: scale its SVG from the start point (compositor) rather than animating
    // stroke-dashoffset (main-thread repaint every frame). Looks identical: solid, non-scaling stroke.
    const line = [...conn.querySelectorAll<HTMLElement>(".flow-conn-h, .flow-conn-v")].find((element) => shown(element));
    if (line) add(line, { transform: desktop ? ["scaleX(0)", "scaleX(1)"] : ["scaleY(0)", "scaleY(1)"] }, { at, duration: duration.connector, ease: easeEntrance });
    add(conn.querySelector(".flow-arrow"), { opacity: [0, 1] }, { at: at + duration.connector * 0.8, duration: 0.15 });
    const dot = conn.querySelector("[data-flow-dot]");
    const length = desktop ? (conn as HTMLElement).clientWidth : (conn as HTMLElement).clientHeight;
    add(
      dot,
      desktop
        ? { opacity: [0, 1, 1, 0], transform: ["translateX(0px)", `translateX(${length}px)`] }
        : { opacity: [0, 1, 1, 0], transform: ["translateY(0px)", `translateY(${length}px)`] },
      { at, duration: duration.connector, ease: easeEntrance },
    );
    return at + duration.connector;
  };

  const chain = (elements: Element[], at: number) => {
    // Nodes and connectors in DOM order; each node lands as its connector arrives.
    let t = at;
    for (const element of elements) {
      if (!shown(element)) continue;
      if (element.hasAttribute("data-flow-conn")) {
        t = connector(element, t) - 0.12;
      } else {
        nodeIn(element, t);
        const check = element.querySelector("[data-flow-check]");
        if (check) {
          segments.push([check, { opacity: [0, 1], transform: ["scale(0)", "scale(1)"] }, { at: t + 0.45, type: "spring", stiffness: 420, damping: 16 }]);
          animated.push(check as HTMLElement);
        }
        t += duration.entrance * 0.6;
      }
    }
    return t;
  };
  const partsOf = (element: Element) => [...element.querySelectorAll("[data-flow-node], [data-flow-conn]")];

  // Linear path: everything in the grid before the fork
  const grid = root.querySelector(".flow-grid")!;
  const children = [...grid.children];
  const forkIndex = children.findIndex((child) => child.classList.contains("flow-fork"));
  const t = chain(children.slice(0, forkIndex).flatMap(partsOf), 0);

  // Fork arms (desktop), then each branch, 120ms apart
  const fork = root.querySelector<HTMLElement>(".flow-fork")!;
  [...root.querySelectorAll("[data-flow-branch]")].forEach((branch, index) => {
    const start = t + index * stagger.branches;
    let branchAt = start;
    if (desktop) {
      const arm = root.querySelector<SVGPathElement>(`[data-flow-arm="${index}"]`);
      add(arm, { strokeDashoffset: [1, 0] }, { at: start, duration: duration.connector, ease: easeEntrance });
      const dot = fork.querySelectorAll("[data-flow-dot]")[index];
      if (arm && dot) {
        // Sample the curve so the dot follows the arm exactly
        const total = arm.getTotalLength();
        const points = Array.from({ length: 13 }, (_, i) => {
          const point = arm.getPointAtLength((total * i) / 12);
          return `translate(${(point.x / 100) * fork.clientWidth}px, ${(point.y / 100) * fork.clientHeight}px)`;
        });
        add(dot, { opacity: [0, 1, 1, 0], transform: points }, { at: start, duration: duration.connector, ease: easeEntrance });
      }
      add(branch.querySelector(".flow-branch-arrow"), { opacity: [0, 1] }, { at: start + duration.connector * 0.8, duration: 0.15 });
      branchAt = start + duration.connector - 0.12;
    }
    chain(partsOf(branch), branchAt);
  });

  for (const element of animated) element.style.willChange = "transform, opacity";
  await Promise.all(segments.map(start));
  root.setAttribute("data-revealed", "");
  // The revealed CSS is the final state now; drop the finished (filled) animations.
  for (const element of animated) for (const animation of element.getAnimations()) animation.cancel();
  requestAnimationFrame(() =>
    requestAnimationFrame(() => {
      for (const element of animated) {
        element.style.removeProperty("opacity");
        element.style.removeProperty("transform");
        element.style.removeProperty("stroke-dashoffset");
        element.style.removeProperty("will-change");
      }
    }),
  );
}
