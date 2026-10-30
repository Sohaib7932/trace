import { ArrowDown, ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost";

const sizes = {
  md: "min-h-11 rounded-[11px] px-5 text-[0.9375rem]",
  sm: "min-h-9 rounded-[10px] px-3.5 text-[0.8125rem]",
} as const;

const base =
  "group inline-flex items-center justify-center gap-2 font-medium tracking-[-0.01em] whitespace-nowrap transition-[background-color,border-color,color,box-shadow,translate] duration-[180ms] ease-[var(--ease-ui)] active:translate-y-px";

const variants: Record<Variant, string> = {
  // Graphite text on orange: 7:1 contrast. White on #FF8139 would be 2.5:1.
  primary:
    "bg-[linear-gradient(180deg,#ff934f_0%,#ff7a2e_100%)] text-foreground font-semibold shadow-[inset_0_1px_0_rgba(255,255,255,0.45),0_1px_2px_rgba(150,60,10,0.25),0_8px_20px_-8px_rgba(255,122,46,0.6)] hover:-translate-y-px hover:bg-[linear-gradient(180deg,#ffa066_0%,#ff8640_100%)] hover:shadow-[inset_0_1px_0_rgba(255,255,255,0.5),0_2px_4px_rgba(150,60,10,0.22),0_12px_24px_-10px_rgba(255,122,46,0.65)] active:translate-y-0",
  secondary:
    "border border-border-strong bg-surface text-foreground shadow-[0_1px_2px_rgba(21,25,35,0.05)] hover:border-foreground/30 hover:bg-surface-muted active:bg-border",
  ghost: "text-foreground hover:bg-foreground/5",
};

export function ButtonLink({
  href,
  children,
  variant = "primary",
  size = "md",
  icon,
  className = "",
}: {
  href: string;
  children: ReactNode;
  variant?: Variant;
  size?: keyof typeof sizes;
  icon?: "right" | "down";
  className?: string;
}) {
  const Icon = icon === "down" ? ArrowDown : ArrowRight;
  const motion =
    icon === "down"
      ? "group-hover:translate-y-0.5"
      : "group-hover:translate-x-0.5";
  return (
    <a href={href} className={`${base} ${sizes[size]} ${variants[variant]} ${className}`}>
      {children}
      {icon && (
        <Icon
          aria-hidden="true"
          className={`size-4 transition-transform duration-200 ease-[var(--ease-ui)] ${motion}`}
          strokeWidth={1.8}
        />
      )}
    </a>
  );
}
