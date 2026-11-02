import { useState } from "react";
import { ChangeStep } from "@/components/learning/forms";
import { EditableRequest } from "@/components/learning/editable-request";
import { attemptBody, ORIGINAL, type Family } from "@/lib/learning/edits";

export const NOTES_CODE = 'payload = {\n    "title": note.title,\n    "body": note.content,\n}\nresponse = client.post("/notes", json=payload)';
export const TASKS_CODE = 'payload = {\n    "title": task.title,\n    "priority": task.priority,\n}\nresponse = client.post("/tasks", json=payload)';

/** The same wiring the workspace uses: in-code edit + one bounded attempt body. */
export function ChangeHarness({ family, investigated = true, onSubmit }: { family: Family; investigated?: boolean; onSubmit: (body: unknown) => void }) {
  const [value, setValue] = useState<string>(ORIGINAL[family]);
  const mustRunOriginal = family === "tasks" && !investigated;
  const shown = mustRunOriginal ? ORIGINAL.tasks : value;
  return <>
    <EditableRequest file="request_builder.py" lines={(family === "notes" ? NOTES_CODE : TASKS_CODE).split("\n")} family={family} value={shown} onChange={setValue} editing locked={mustRunOriginal} disabled={false} />
    <ChangeStep family={family} changed={!mustRunOriginal && value !== ORIGINAL[family]} mustRunOriginal={mustRunOriginal} pending={false}
      onReset={() => setValue(ORIGINAL[family])} onCheck={(explanation) => onSubmit(attemptBody(family, shown, explanation))} />
  </>;
}
