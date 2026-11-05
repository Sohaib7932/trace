import { AlertTriangle, Check, CircleDashed, Loader2, Lock, X } from "lucide-react";
import type { ReactNode } from "react";
import { languageStyle, shortSha } from "@/lib/projects/format";

/** Everything here renders repository text as plain text. Names, paths and code are untrusted. */

export function RepoName({ fullName, className = "" }: { fullName: string; className?: string }) {
  return <span className={`pj-mono block min-w-0 truncate ${className}`} title={fullName}>{fullName}</span>;
}

export function ShaChip({ sha }: { sha: string }) {
  return <span className="pj-chip pj-mono" title={sha}><span className="sr-only">Commit </span>{shortSha(sha)}</span>;
}

export function PathChip({ path }: { path: string }) {
  return <span className="pj-chip pj-mono max-w-full min-w-0 truncate" title={path}>{path}</span>;
}

export function LanguageChip({ name, files }: { name: string; files?: number }) {
  return <span className="pj-chip" style={languageStyle(name)}>{name}{files !== undefined && <span className="opacity-70"> · {files}</span>}</span>;
}

export function PrivateChip({ isPrivate }: { isPrivate: boolean }) {
  return (
    <span className="pj-chip">
      {isPrivate && <Lock aria-hidden="true" className="size-3" strokeWidth={2} />}
      {isPrivate ? "Private" : "Public"}
    </span>
  );
}

type Tone = "ok" | "warn" | "off" | "work";
export function StatusChip({ tone, children }: { tone: Tone; children: ReactNode }) {
  const Icon = tone === "ok" ? Check : tone === "warn" ? AlertTriangle : tone === "work" ? Loader2 : CircleDashed;
  return (
    <span className={`pj-chip pj-status pj-status-${tone}`}>
      <Icon aria-hidden="true" className={`size-3 ${tone === "work" ? "pj-spin" : ""}`} strokeWidth={2.2} />
      {children}
    </span>
  );
}

/** One source excerpt: file path, line range and commit are always shown with it. */
export function Excerpt({ path, text, sha, lineStart, lineEnd, note, id }: {
  path: string; text: string; sha: string; lineStart?: number; lineEnd?: number; note?: ReactNode; id?: string;
}) {
  const lines = lineStart !== undefined && lineEnd !== undefined ? (lineStart === lineEnd ? `Line ${lineStart}` : `Lines ${lineStart}–${lineEnd}`) : "Line range not provided";
  return (
    <figure id={id} className="pj-excerpt">
      <figcaption>
        <PathChip path={path} />
        <span className="pj-chip">{lines}</span>
        <ShaChip sha={sha} />
      </figcaption>
      <pre tabIndex={0} aria-label={`Source excerpt from ${path}`}>{text}</pre>
      {note && <p className="pj-excerpt-note">{note}</p>}
    </figure>
  );
}

export type Stage = { id: string; label: string; detail: string; state: "done" | "active" | "todo" | "failed" | "unavailable" };

/** The path a project takes: each stage has an icon and a word, never colour alone. */
export function PipelineTracker({ stages }: { stages: Stage[] }) {
  const done = stages.filter((stage) => stage.state === "done").length;
  return (
    <ol className="pj-pipeline" aria-label="Progress" style={{ "--fill": stages.length > 1 ? done / (stages.length - 1) : 0 } as React.CSSProperties}>
      {stages.map((stage, index) => {
        const Icon = stage.state === "done" ? Check : stage.state === "failed" ? X : stage.state === "active" ? Loader2 : CircleDashed;
        return (
          <li key={stage.id} data-state={stage.state} style={{ "--k": index } as React.CSSProperties} aria-current={stage.state === "active" ? "step" : undefined}>
            <span aria-hidden="true" className="pj-node"><Icon className={`size-4 ${stage.state === "active" ? "pj-spin" : ""}`} strokeWidth={2.2} /></span>
            <span className="pj-stage-label">{stage.label}
              <span className="sr-only"> ({stage.state === "done" ? "done" : stage.state === "active" ? "in progress" : stage.state === "failed" ? "failed" : stage.state === "unavailable" ? "not available" : "not started"})</span>
            </span>
            <span className="pj-stage-detail">{stage.detail}</span>
          </li>
        );
      })}
    </ol>
  );
}
