import { beforeEach, expect, test, vi } from "vitest";

const fx = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ protectedApiRequest: fx.request }));

import { realLeaderboard } from "@/lib/leaderboard/client";

beforeEach(() => fx.request.mockReset());

test("the real board asks only for a page size and an opaque cursor, as a GET with no body", async () => {
  fx.request.mockResolvedValue({ entries: [], next_cursor: null, me: null, generated_at: "2026-11-05T08:00:00Z" });
  await realLeaderboard.page({ limit: 20 });
  expect(fx.request).toHaveBeenNthCalledWith(1, "/leaderboard?limit=20", undefined, undefined, undefined);
  const controller = new AbortController();
  await realLeaderboard.page({ limit: 5, cursor: "abc def" }, controller.signal);
  expect(fx.request).toHaveBeenNthCalledWith(2, "/leaderboard?limit=5&cursor=abc+def", undefined, undefined, controller.signal);
});
