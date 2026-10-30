import type { FlowBranch, FlowNode } from "@/components/marketing/flow-diagram";

/**
 * The shared Express example traced as a flow. Labels are real code; statuses are
 * sample output, and the diagram labels them "Sample run".
 */

export const loopPath: FlowNode[] = [
  { kicker: "Request", title: "POST /notes", detail: "a JSON body" },
  { kicker: "Read", title: "express.json()", detail: "reads the body" },
  { kicker: "Check", title: "if (!title)", detail: "is there a title?" },
];

export const loopBranches: [FlowBranch, FlowBranch] = [
  {
    label: "title present",
    nodes: [
      { kicker: "Save", title: "notes.push(title)", detail: "adds it to notes" },
      { kicker: "Reply", title: "201 Created", tone: "success" },
    ],
  },
  {
    label: "title missing",
    nodes: [{ kicker: "Reply", title: "400 Bad Request", detail: "stops here, saves nothing", tone: "error" }],
  },
];

/** The walkthrough's request has no title, so the save branch is never reached. */
export const walkthroughPath: FlowNode[] = [
  { kicker: "Request", title: "POST /notes", detail: "body: {}" },
  { kicker: "Read", title: "express.json()", detail: "reads the body" },
  { kicker: "Check", title: "if (!title)", detail: "no title found" },
];

export const walkthroughBranches: [FlowBranch, FlowBranch] = [
  { ...loopBranches[0], dim: true, dimNote: "Not reached for this request" },
  loopBranches[1],
];
