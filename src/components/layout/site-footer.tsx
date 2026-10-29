import { Wordmark } from "@/components/brand/trace-mark";

const links = [
  { href: "#demo", label: "Demo lesson" },
  { href: "#how-it-works", label: "How it works" },
  { href: "#walkthrough", label: "Walkthrough" },
  { href: "#progress", label: "Learning approach" },
];

export function SiteFooter() {
  return (
    <footer className="border-t border-border">
      <div className="shell flex flex-col gap-8 py-10 md:flex-row md:items-center md:justify-between">
        <div className="max-w-[22rem]">
          <Wordmark />
          <p className="mt-3 text-[0.875rem] leading-relaxed text-secondary">
            Understand the code, then direct the agent.
          </p>
        </div>
        <nav aria-label="Footer">
          <ul className="grid grid-cols-2 gap-x-10 gap-y-1 sm:flex sm:gap-x-2">
            {links.map((link) => (
              <li key={link.href}>
                <a
                  href={link.href}
                  className="inline-flex min-h-11 items-center rounded-md text-[0.875rem] text-secondary transition-colors hover:text-foreground sm:px-3"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      </div>
      <div className="shell border-t border-border py-5">
        <p className="text-[0.8125rem] leading-5 text-secondary">
          Trace is a prototype. Lesson results on this page are sample output, not live runs.
        </p>
      </div>
    </footer>
  );
}
