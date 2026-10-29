import type { CSSProperties, ElementType, ReactNode } from "react";
import type { RevealVariant } from "@/lib/motion/tokens";

/**
 * Marks content for a scroll reveal. Server-rendered and JS-free: it only adds
 * data attributes. The motion runtime animates it once it enters the viewport.
 *
 * - Plain: the element itself reveals.
 * - `stagger`: the element stays put and its [data-reveal-item] descendants reveal in turn.
 *   Inside each item, [data-reveal-inner] parts get a short secondary reveal.
 */
export function Reveal({
  as: Tag = "div",
  variant = "up",
  stagger = false,
  delay = 0,
  className = "",
  style,
  children,
  ...rest
}: {
  as?: ElementType;
  variant?: RevealVariant;
  stagger?: boolean;
  /** ms */
  delay?: number;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
} & Partial<Record<`data-${string}` | `aria-${string}` | "id" | "role", string>>) {
  return (
    <Tag
      {...rest}
      data-reveal={stagger ? undefined : variant}
      data-reveal-stagger={stagger ? variant : undefined}
      style={{ ...style, "--d": `${delay}ms` } as CSSProperties}
      className={className}
    >
      {children}
    </Tag>
  );
}
