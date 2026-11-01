import { ArrowRight } from "lucide-react";
import { SplitHeading } from "@/components/motion/split-heading";
import { ButtonLink } from "@/components/ui/button-link";
import { DeviceSequence } from "./device-sequence";

export function Hero() {
  return (
    <section id="top" aria-labelledby="hero-title" className="relative">
      <div className="shell relative z-10 pt-[clamp(44px,6vw,84px)] text-center">
        <div className="enter" style={{ "--d": "60ms" } as React.CSSProperties}>
          <a
            href="#how-it-works"
            className="group inline-flex max-w-full items-center gap-2.5 rounded-[14px] border sm:rounded-full border-border bg-surface py-1 pr-1 pl-3.5 shadow-[0_1px_2px_rgba(21,25,35,0.04)] transition-colors hover:border-border-strong"
          >
            <span className="text-left text-[0.6875rem] leading-snug font-medium tracking-[0.08em] text-secondary uppercase sm:text-[0.75rem]">
              The gap between shipping and understanding
            </span>
            <span
              aria-hidden="true"
              className="chip-pulse-load flex size-[22px] shrink-0 items-center justify-center rounded-[7px] bg-[linear-gradient(180deg,#ff934f,#ff7a2e)] text-white"
              style={{ "--d": "260ms" } as React.CSSProperties}
            >
              <ArrowRight className="size-3.5 transition-transform duration-200 group-hover:translate-x-px" strokeWidth={2.2} />
            </span>
          </a>
        </div>

        {/* Load-mode word reveal: CSS keyframes from first paint, no wait for hydration (LCP) */}
        <SplitHeading
          as="h1"
          id="hero-title"
          mode="load"
          baseDelay={140}
          className="type-display mx-auto mt-6 max-w-[12ch] text-foreground sm:max-w-none"
          segments={["You can build with AI.", { br: true }, "Now ", { accent: "understand" }, " the code."]}
        />

        <p
          className="enter mx-auto mt-5 max-w-[540px] text-[1rem] leading-relaxed text-balance text-secondary sm:text-[1.0625rem]"
          style={{ "--d": "400ms" } as React.CSSProperties}
        >
          Predict, change, and verify real code, including code an agent wrote, so you can debug
          the next problem yourself.
        </p>

        {/* Secondary left, primary right; on phones the primary stacks on top */}
        <div
          className="enter mt-8 flex flex-col-reverse items-center justify-center gap-3 sm:flex-row"
          style={{ "--d": "500ms" } as React.CSSProperties}
        >
          <ButtonLink href="#demo" variant="secondary" className="w-full sm:w-auto">
            See how Trace works
          </ButtonLink>
          <ButtonLink href="/learn" icon="right" className="w-full sm:w-auto">
            Try a lesson
          </ButtonLink>
        </div>
      </div>

      <DeviceSequence />
    </section>
  );
}
