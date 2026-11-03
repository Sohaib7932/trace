import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { DemoLabel } from "@/components/ai/demo-label";
import { InterestPicker } from "@/components/daily/interest-picker";

// In real mode only features with a real endpoint (tutor, Trace Help) drop the demo label.
// Interests and daily exercises have no endpoint, so they stay the labelled demo, never an error.
beforeEach(() => { vi.stubEnv("NEXT_PUBLIC_AI_MODE", "real"); localStorage.clear(); });
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

test("a label follows the mode of the client that drives its surface", () => {
  const { rerender } = render(<DemoLabel />);
  expect(screen.queryByRole("button", { name: /Demo responses/ })).toBeNull();
  rerender(<DemoLabel text="Demo exercise" mode="mock" />);
  expect(screen.getByRole("button", { name: /Demo exercise/ })).toBeVisible();
});

test("in real mode the interest picker stays a labelled demo and makes no request", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  render(<InterestPicker />);
  expect(await screen.findByRole("button", { name: /Demo-only/ })).toBeVisible();
  expect(await screen.findByRole("button", { name: "Fitness tracking" })).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(fetch).not.toHaveBeenCalled();
});
