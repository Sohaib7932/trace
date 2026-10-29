import { ArrowRight } from "lucide-react";
import { ButtonLink } from "@/components/ui/button-link";
import { LessonDemo } from "./lesson-demo";
import { LightStreaks } from "./light-streaks";

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
              className="flex size-[22px] shrink-0 items-center justify-center rounded-[7px] bg-[linear-gradient(180deg,#ff934f,#ff7a2e)] text-white"
            >
              <ArrowRight className="size-3.5 transition-transform duration-200 group-hover:translate-x-px" strokeWidth={2.2} />
            </span>
          </a>
        </div>

        <h1
          id="hero-title"
          className="type-display enter mx-auto mt-6 max-w-[12ch] text-foreground sm:max-w-none"
          style={{ "--d": "140ms" } as React.CSSProperties}
        >
          You can build with&nbsp;AI.
          <br className="hidden sm:block" />{" "}
          Now <span className="text-primary-display">understand</span> the&nbsp;code.
        </h1>

        <p
          className="enter mx-auto mt-5 max-w-[540px] text-[1rem] leading-relaxed text-balance text-secondary sm:text-[1.0625rem]"
          style={{ "--d": "260ms" } as React.CSSProperties}
        >
          Predict, change, and verify real code, including code an agent wrote, so you can debug
          the next problem yourself.
        </p>

        {/* Secondary left, primary right; on phones the primary stacks on top */}
        <div
          className="enter mt-8 flex flex-col-reverse items-center justify-center gap-3 sm:flex-row"
          style={{ "--d": "360ms" } as React.CSSProperties}
        >
          <ButtonLink href="#how-it-works" variant="secondary" className="w-full sm:w-auto">
            See how Trace works
          </ButtonLink>
          <ButtonLink href="#demo" icon="down" className="w-full sm:w-auto">
            Try a lesson
          </ButtonLink>
        </div>
      </div>

      <div
        id="demo"
        className="enter relative mx-auto mt-[clamp(72px,7vw,96px)] w-[min(calc(100%-2*var(--gutter)),1100px)] lg:w-[min(80%,1100px)]"
        style={{ "--d": "480ms" } as React.CSSProperties}
      >
        <LightStreaks />
        <div aria-hidden="true" className="showcase-glow" />
        <div className="relative z-10">
          <h2 className="sr-only">Try a sample lesson</h2>
          <LessonDemo />
        </div>
      </div>
    </section>
  );
}
