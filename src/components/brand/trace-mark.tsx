/** The Trace mark: a signal path from an input node to a lit outcome node. */
export function TraceMark({ className = "" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <circle cx="5" cy="6" r="2.25" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M7.2 6.6h3.3c1.7 0 2.5.9 2.5 2.6v5.6c0 1.7.8 2.6 2.5 2.6h1.3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <circle cx="19" cy="17.4" r="2.6" fill="var(--primary)" />
    </svg>
  );
}

export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <TraceMark className="size-[22px]" />
      <span className="text-[1.0625rem] font-semibold tracking-[-0.04em]">trace</span>
    </span>
  );
}
