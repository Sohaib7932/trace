import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import { MobileNav } from "@/components/layout/mobile-nav";
import { ButtonLink } from "@/components/ui/button-link";

test("mobile navigation opens, moves focus, and closes on Escape", async () => {
  const user = userEvent.setup();
  render(<MobileNav />);
  const toggle = screen.getByRole("button", { name: "Open menu" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getAllByRole("link")[0]).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveFocus();
});

test("navigation closes after selecting its real in-page destination", async () => {
  const user = userEvent.setup();
  render(<MobileNav />);
  await user.click(screen.getByRole("button", { name: "Open menu" }));
  const destination = screen.getAllByRole("link")[0];
  // Section links include the path so they also work from other pages; "/learn" is the lessons hub.
  expect(destination.getAttribute("href")).toMatch(/^\/(#[a-z-]+|learn)$/);
  await user.click(destination);
  expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute("aria-expanded", "false");
});

test("CTA retains its accessible name and real destination with a decorative icon", () => {
  render(<ButtonLink href="#demo" icon="down">Try a lesson</ButtonLink>);
  expect(screen.getByRole("link", { name: "Try a lesson" })).toHaveAttribute("href", "#demo");
});
