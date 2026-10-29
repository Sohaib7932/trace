const principles = ["Real code", "Predict first", "Verify with evidence", "Practise again"];

export function Principles() {
  return (
    <section aria-label="Principles" className="shell mt-[clamp(56px,7vw,96px)]">
      <div
        data-reveal="fade"
        className="flex flex-col gap-5 border-y border-border py-7 md:flex-row md:items-center md:gap-10 md:border-y-0 md:py-0"
      >
        <p className="shrink-0 text-[0.875rem] leading-snug text-secondary md:max-w-[11.5rem]">
          Built around <span className="font-medium text-primary-ink">four habits</span> you keep
          after the lesson
        </p>
        <span aria-hidden="true" className="hidden h-11 w-px shrink-0 bg-border-strong md:block" />
        <ul className="grid flex-1 grid-cols-2 gap-x-6 gap-y-4 md:flex md:items-center md:justify-between">
          {principles.map((label, index) => (
            <li key={label} className="flex items-baseline gap-2.5">
              <span aria-hidden="true" className="font-mono text-[0.6875rem] text-tertiary">
                0{index + 1}
              </span>
              <span className="text-[0.8125rem] font-semibold tracking-[0.08em] text-secondary uppercase sm:text-[0.875rem]">
                {label}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
