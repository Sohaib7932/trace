import { notFound } from "next/navigation";
import { PageHead } from "@/components/projects/page-head";
import { Excerpt, PipelineTracker, ShaChip, type Stage } from "@/components/projects/parts";

export const metadata = { title: "Projects demo · Trace" };

const STAGES: Stage[] = [
  { id: "connected", label: "Connected", state: "done", detail: "Read-only access (demo)." },
  { id: "pinned", label: "Commit pinned", state: "done", detail: "A made-up commit." },
  { id: "fetch", label: "Fetching", state: "done", detail: "Snapshot saved (demo)." },
  { id: "index", label: "Indexing", state: "done", detail: "Repository read (demo)." },
  { id: "analyze", label: "Analyzing", state: "active", detail: "Writing questions (demo)." },
  { id: "ready", label: "Path ready", state: "todo", detail: "Not generated." },
];
const SHA = "0123456789abcdef0123456789abcdef01234567";

/** Off unless NEXT_PUBLIC_PROJECTS_DEMO=1. Everything here is made up and labelled. */
export default function ProjectsDemoPage() {
  if (process.env.NEXT_PUBLIC_PROJECTS_DEMO !== "1") notFound();
  return (
    <>
      <PageHead title={["Projects, ", { accent: "demo" }]}>Made-up data so you can see the screens. Nothing on this page comes from GitHub or the server.</PageHead>
      <p role="note" className="pj-chip mb-5">Demo · sample data</p>
      <section aria-label="Sample project" className="pj-card grid gap-6 p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-2"><span className="pj-mono font-medium">demo-user/notes-api</span><ShaChip sha={SHA} /></div>
        <PipelineTracker stages={STAGES} />
        <Excerpt path="src/routes/notes.js" sha={SHA} lineStart={6} lineEnd={9} text={'app.post("/notes", (req, res) => {\n  const title = req.body?.title;\n  if (!title) return res.status(400).json({ error: "no title" });\n  notes.push(title);'} note="Sample excerpt (demo)." />
      </section>
    </>
  );
}
