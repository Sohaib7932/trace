import { Wordmark } from "@/components/brand/trace-mark";
import { ButtonLink } from "@/components/ui/button-link";
import { MobileNav } from "./mobile-nav";
import { NavScroll } from "./nav-scroll";
import { navLinks, primaryCta } from "./nav-links";

export function SiteHeader() {
  return (
    <header id="site-header" className="site-header enter-down sticky top-0 z-40 px-3 pt-3 sm:px-4 sm:pt-[18px]">
      <nav
        aria-label="Main"
        className="relative mx-auto flex h-[58px] w-full max-w-[1100px] items-center justify-between rounded-[14px] border border-border bg-surface pr-2 pl-4 shadow-[0_1px_2px_rgba(21,25,35,0.04),0_10px_30px_-18px_rgba(21,25,35,0.18)] sm:pl-5 lg:w-[78%]"
      >
        <div className="flex items-center gap-6 lg:gap-8">
          <a href="#top" className="rounded-md text-foreground" aria-label="Trace, back to top">
            <Wordmark />
          </a>

          <ul className="hidden items-center gap-0.5 md:flex">
          {navLinks.map((link) => (
            <li key={link.href}>
              <a
                href={link.href}
                className="rounded-lg px-3 py-2 text-[0.875rem] font-medium tracking-[-0.01em] text-secondary transition-colors duration-150 hover:text-foreground"
              >
                {link.label}
              </a>
            </li>
          ))}
          </ul>
        </div>

        <div className="flex items-center gap-1">
          <ButtonLink href={primaryCta.href} size="sm">
            {primaryCta.label}
          </ButtonLink>
          <MobileNav />
        </div>
      </nav>
      <NavScroll />
    </header>
  );
}
