import type { FlowBranch, FlowNode } from "@/components/marketing/flow-diagram";

/**
 * Request flows for <FlowDiagram>. The labels are real FastAPI concepts; statuses and
 * results are sample output and the diagram labels them "Sample run".
 */

export const loopPath: FlowNode[] = [
  { kicker: "Request", title: "POST /notes", detail: "JSON body" },
  { kicker: "FastAPI", title: "Pydantic validation", detail: "builds NoteIn" },
];

export const loopBranches: [FlowBranch, FlowBranch] = [
  {
    label: "title present",
    nodes: [
      { kicker: "Handler", title: "db.add + commit", detail: "row written" },
      { kicker: "Response", title: "201 Created", tone: "success" },
    ],
  },
  {
    label: "title missing",
    nodes: [{ kicker: "Response", title: "422 Unprocessable", detail: "handler never runs", tone: "error" }],
  },
];

/** The walkthrough's request has no title, so the success branch is never reached. */
export const walkthroughPath: FlowNode[] = [
  { kicker: "Request", title: "POST /notes", detail: '{ "content": … }' },
  { kicker: "FastAPI", title: "Pydantic validation", detail: "title missing" },
];

export const walkthroughBranches: [FlowBranch, FlowBranch] = [
  { ...loopBranches[0], dim: true, dimNote: "Not reached for this request" },
  loopBranches[1],
];
