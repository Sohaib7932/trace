"use client";

import { ChevronDown, CornerDownRight, Lock, Undo2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { CodeRow, indentOf } from "@/components/code/code-lines";
import { CodeText } from "@/components/code/code-line";
import { editRows, NOTES_FIELDS, type Family } from "@/lib/learning/edits";

/**
 * The lesson's request code with the change made INSIDE the code (like the homepage demo).
 * The control can only produce the backend's bounded values (Notes: body | content;
 * Tasks: flat | nested); no code text is ever sent.
 */
export function EditableRequest({ file, lines, family, value, onChange, editing, locked, disabled }: {
  file: string;
  lines: string[];
  family: Family;
  value: string;
  onChange: (value: string) => void;
  /** The session accepts a change now (ready_for_attempt / needs_revision). */
  editing: boolean;
  /** Tasks: the nested edit is locked until the original flat request has a real failed run. */
  locked: boolean;
  disabled: boolean;
}) {
  const rows = editRows(lines, family, editing ? value : family === "notes" ? "body" : "flat");
  const body = (
    <code className="block">
      {rows.map((row) => (
        <CodeRow key={row.key} number={row.number} kind={row.kind} wrap indent={indentOf(row.source)} className={row.kind === "added" ? "code-row-enter" : ""} data-edit-row={row.control ? "" : undefined}>
          {row.control && editing
            ? family === "notes" ? <NotesLine source={row.source} value={value} onChange={onChange} disabled={disabled} />
              : <TasksLine source={row.source} nested={value === "nested"} onChange={onChange} locked={locked} disabled={disabled} />
            : <CodeText source={row.source} />}
        </CodeRow>
      ))}
    </code>
  );
  return (
    <CodeWindow
      file={file}
      lang="Python"
      lines={lines}
      wrap
      body={body}
      note={editing
        ? "You edit this line inside the code. Trace checks a fixed set of changes against the real server."
        : family === "tasks" ? "Trace task.priority and each JSON level." : "Follow note.content into the outgoing dictionary."}
    />
  );
}

/** Notes: the dictionary key is a chip; choosing a name rewrites the line live. */
function NotesLine({ source, value, onChange, disabled }: { source: string; value: string; onChange: (v: string) => void; disabled: boolean }) {
  const match = /^(.*?")(body|content)("\s*:.*)$/.exec(source);
  if (!match) return <CodeText source={source} />;
  return <>{match[1]}<FieldChip value={value} onChange={onChange} disabled={disabled} /><CodeText source={match[3]} /></>;
}

function FieldChip({ value, onChange, disabled }: { value: string; onChange: (v: string) => void; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(Math.max(0, NOTES_FIELDS.indexOf(value as (typeof NOTES_FIELDS)[number])));
  const chip = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const listId = useId();

  useEffect(() => {
    if (!open) return;
    list.current?.focus();
    const outside = (event: PointerEvent) => {
      if (!list.current?.contains(event.target as Node) && !chip.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);

  function close(pick?: string) {
    if (pick) onChange(pick);
    setOpen(false);
    chip.current?.focus();
  }
  function onKey(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown" || event.key === "ArrowRight") { event.preventDefault(); setActive((i) => (i + 1) % NOTES_FIELDS.length); }
    else if (event.key === "ArrowUp" || event.key === "ArrowLeft") { event.preventDefault(); setActive((i) => (i - 1 + NOTES_FIELDS.length) % NOTES_FIELDS.length); }
    else if (event.key === "Home") { event.preventDefault(); setActive(0); }
    else if (event.key === "End") { event.preventDefault(); setActive(NOTES_FIELDS.length - 1); }
    else if (event.key === "Enter" || event.key === " ") { event.preventDefault(); close(NOTES_FIELDS[active]); }
    else if (event.key === "Escape" || event.key === "Tab") { event.preventDefault(); close(); }
  }

  return (
    <span className="relative inline-block indent-0">
      <button
        ref={chip}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listId : undefined}
        aria-label={`Change field name, currently ${value}`}
        onClick={() => { setActive(Math.max(0, NOTES_FIELDS.indexOf(value as (typeof NOTES_FIELDS)[number]))); setOpen((o) => !o); }}
        onKeyDown={(e) => { if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); } }}
        className="code-chip"
      >
        <span className="tok-str">{value}</span>
        <ChevronDown aria-hidden="true" className="size-3.5" strokeWidth={2.2} />
      </button>
      {open && (
        <ul ref={list} id={listId} role="listbox" tabIndex={-1} aria-label="Field name" aria-activedescendant={`${listId}-${NOTES_FIELDS[active]}`} onKeyDown={onKey} className="code-popover">
          {NOTES_FIELDS.map((field, index) => (
            <li
              key={field}
              id={`${listId}-${field}`}
              role="option"
              aria-selected={field === value}
              data-active={index === active ? "" : undefined}
              onMouseEnter={() => setActive(index)}
              onClick={() => close(field)}
              className="code-option"
            >
              <span className="font-mono">&quot;{field}&quot;</span>
              {field === value && <span className="text-[0.75rem] text-secondary">current</span>}
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}

/** Tasks: an inline control rewrites the payload between flat and nested in place. */
function TasksLine({ source, nested, onChange, locked, disabled }: { source: string; nested: boolean; onChange: (v: string) => void; locked: boolean; disabled: boolean }) {
  const hint = useId();
  return (
    <>
      <CodeText source={source} />{" "}
      <span className="inline-flex flex-wrap items-center gap-1.5 align-middle indent-0">
        {nested ? (
          <button type="button" className="code-chip" disabled={disabled} onClick={() => onChange("flat")}>
            <Undo2 aria-hidden="true" className="size-3.5" strokeWidth={2} />Undo nesting
          </button>
        ) : (
          <button type="button" className="code-chip" disabled={disabled || locked} aria-describedby={locked ? hint : undefined} onClick={() => onChange("nested")}>
            {locked ? <Lock aria-hidden="true" className="size-3.5" strokeWidth={2} /> : <CornerDownRight aria-hidden="true" className="size-3.5" strokeWidth={2} />}Nest this field
          </button>
        )}
        {locked && !nested && <span id={hint} className="font-sans text-[0.75rem] text-secondary">Run the original request first</span>}
      </span>
    </>
  );
}
