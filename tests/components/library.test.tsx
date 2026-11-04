import { expect, test } from "vitest";
import type { CustomLessonSummary } from "@/lib/api/client";
import { continueLesson, filterLessons, lessonStatus } from "@/lib/learning/library";

const summary = (id: string, overrides: Partial<CustomLessonSummary> = {}): CustomLessonSummary => ({
  id, request_id: `req-${id}`, position: 1, title: `Lesson ${id}`, objective: "Read a request.", language: "Python",
  level: "beginner", created_at: "2026-11-04T10:00:00Z", challenge_count: 3, completed_challenges: 0, ...overrides,
});

test("status comes from server progress; filters search title, language and level; sorting is stable", () => {
  const items = [
    summary("a", { title: "Express routes", language: "JavaScript", created_at: "2026-11-01T10:00:00Z" }),
    summary("b", { title: "FastAPI bodies", completed_challenges: 1, created_at: "2026-11-03T10:00:00Z" }),
    summary("c", { title: "SQL joins", language: "SQL", level: "advanced", completed_challenges: 3, created_at: "2026-11-02T10:00:00Z" }),
  ];
  expect(items.map(lessonStatus)).toEqual(["not_started", "in_progress", "completed"]);
  const titles = (options: Parameters<typeof filterLessons>[1]) => filterLessons(items, options).map((item) => item.title);
  expect(titles({ query: "", status: "all", sort: "newest" })).toEqual(["FastAPI bodies", "SQL joins", "Express routes"]);
  expect(titles({ query: "", status: "all", sort: "oldest" })).toEqual(["Express routes", "SQL joins", "FastAPI bodies"]);
  expect(titles({ query: "", status: "all", sort: "title" })).toEqual(["Express routes", "FastAPI bodies", "SQL joins"]);
  expect(titles({ query: "javascript", status: "all", sort: "newest" })).toEqual(["Express routes"]);
  expect(titles({ query: "ADVANCED", status: "all", sort: "newest" })).toEqual(["SQL joins"]);
  expect(titles({ query: "", status: "completed", sort: "newest" })).toEqual(["SQL joins"]);
  expect(continueLesson(items)?.title).toBe("FastAPI bodies");
  expect(continueLesson([items[0], items[2]])).toBeUndefined();
});
