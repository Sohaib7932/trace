/**
 * The one shared example used across the homepage (hero demo, feature cards, steps,
 * flow diagram, walkthrough, learning history): a tiny Node + Express route.
 *
 * Verified by running it on Express 5.3.0 and 4.22.3:
 *  - POST /notes with no title  -> 400 {"error":"no title"}, notes stays []
 *    (also with no body at all: Express 5 leaves req.body undefined, Express 4 sets {};
 *    req.body?.title handles both, so there is no crash)
 *  - POST /notes {"title":"Buy milk"} -> 201 {"saved":true}, notes = ["Buy milk"]
 *  - after the Modify step (count: notes.length) -> 201 {"saved":true,"count":1}
 *  - Revisit: POST /tasks with no name -> 400 {"error":"no name"}, tasks stays []
 *
 * Everything shown on the marketing site is sample output, labelled as such.
 * (The platform backend itself is FastAPI; only these displayed snippets are JavaScript.)
 */

export const file = "server.js";
export const lang = "JavaScript · Express";

/** server.js, line by line (line 1 = index 0). */
export const serverLines = [
  'const express = require("express");',
  "const app = express();",
  "app.use(express.json());",
  "const notes = [];",
  "",
  'app.post("/notes", (req, res) => {',
  "  const title = req.body?.title;",
  "  if (!title) {",
  '    return res.status(400).json({ error: "no title" });',
  "  }",
  "  notes.push(title);",
  "  res.status(201).json({",
  "    saved: true,",
  "  });",
  "});",
];

/** Key line numbers in server.js. */
export const line = {
  route: 6,
  readTitle: 7,
  check: 8,
  stop: 9,
  push: 11,
  reply: 12,
  saved: 13,
} as const;

/** Lines `from`..`to` (inclusive, 1-based). */
export function excerpt(from: number, to: number) {
  return serverLines.slice(from - 1, to);
}

/** The Modify step: one new line after `saved: true,`. */
export const change = {
  afterLine: line.saved,
  added: "    count: notes.length,",
  task: "Make the reply also say how many notes are saved.",
};

/** server.js after the change (lines 12–15 of the new file). */
export const changedReply = ["  res.status(201).json({", "    saved: true,", change.added, "  });"];

/** Sample requests and results (written to match the verified behaviour). */
export const sample = {
  noTitle: {
    body: "{}",
    status: "400",
    statusText: "Bad Request",
    response: '{ "error": "no title" }',
    notes: "[]",
  },
  withTitle: {
    body: '{ "title": "Buy milk" }',
    status: "201",
    statusText: "Created",
    response: '{ "saved": true }',
    notes: '["Buy milk"]',
  },
  afterChange: {
    body: '{ "title": "Buy milk" }',
    status: "201",
    statusText: "Created",
    response: '{ "saved": true, "count": 1 }',
    notes: '["Buy milk"]',
  },
};

/** Revisit: the same idea in different code. */
export const revisitLines = [
  "const tasks = [];",
  "",
  'app.post("/tasks", (req, res) => {',
  "  const name = req.body?.name;",
  "  if (!name) {",
  '    return res.status(400).json({ error: "no name" });',
  "  }",
  "  tasks.push(name);",
  "  res.status(201).json({ saved: true });",
  "});",
];

/** Plain-language captions shown under code samples. */
export const caption = {
  route: "This route saves a note. If title is missing, it stops early and sends back 400.",
  stop: "This line checks the request. If title is missing, the function stops here and sends back 400.",
  change: "One new line. The reply now also says how many notes are saved.",
  revisit: "Same idea, new code: a task needs a name. What happens without one?",
};
