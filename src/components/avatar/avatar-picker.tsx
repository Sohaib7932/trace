"use client";

import { Check, X } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useDialog } from "@/components/ai/use-dialog";
import { AVATARS, resolveAvatarId } from "@/lib/avatars/avatars";
import { saveAvatar } from "@/lib/avatars/profile";
import { Avatar } from "./avatar";

const COLUMNS = 4;

/**
 * Choose an avatar from Trace's own set. Arrow keys move between choices, Enter or Space picks,
 * Escape closes. Saving writes `avatar_id` to the signed-in account; if that fails, the choice
 * is kept on this device and the dialog says so.
 */
export function AvatarPicker({ userId, current, onClose }: { userId: string; current: string | null; onClose: () => void }) {
  const [choice, setChoice] = useState(() => resolveAvatarId(current, userId));
  const [state, setState] = useState<"idle" | "saving" | "account" | "device" | "error">("idle");
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const selected = AVATARS.findIndex((avatar) => avatar.id === choice);
  const panel = useDialog(true, () => { if (state !== "saving") onClose(); }, () => buttons.current[Math.max(0, selected)] ?? null);
  const ids = useId();

  function move(event: React.KeyboardEvent, index: number) {
    const moves: Record<string, number> = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: COLUMNS, ArrowUp: -COLUMNS };
    let next = index;
    if (event.key in moves) next = index + moves[event.key];
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = AVATARS.length - 1;
    else return;
    event.preventDefault();
    buttons.current[Math.min(AVATARS.length - 1, Math.max(0, next))]?.focus();
  }

  async function save() {
    setState("saving");
    try { setState(await saveAvatar(userId, choice)); }
    catch { setState("error"); }
  }

  return (
    <>
      <div aria-hidden="true" className="dialog-scrim" onClick={() => { if (state !== "saving") onClose(); }} />
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={`${ids}-title`} className="avatar-dialog">
        <div className="flex items-start justify-between gap-3">
          <h2 id={`${ids}-title`} className="text-[1.125rem] font-semibold">Choose your avatar</h2>
          <button type="button" onClick={onClose} disabled={state === "saving"} aria-label="Close" className="-mt-1 -mr-1 inline-flex size-11 items-center justify-center rounded-lg text-secondary hover:bg-foreground/5"><X aria-hidden="true" className="size-5" strokeWidth={2} /></button>
        </div>
        <div className="mt-3 flex items-center gap-4">
          <Avatar avatarId={choice} seed={userId} size={72} className="avatar-preview" key={choice} />
          <p className="text-[0.875rem] text-secondary">Shown on your account, in the navbar and on the leaderboard.</p>
        </div>
        <div role="group" aria-label="Avatars" className="mt-5 grid grid-cols-4 gap-2 sm:gap-3">
          {AVATARS.map((avatar, index) => (
            <button
              key={avatar.id}
              ref={(node) => { buttons.current[index] = node; }}
              type="button"
              aria-pressed={choice === avatar.id}
              aria-label={avatar.label}
              onClick={() => { setChoice(avatar.id); if (state !== "saving") setState("idle"); }}
              onKeyDown={(event) => move(event, index)}
              className="avatar-choice"
            >
              <Avatar avatarId={avatar.id} seed={userId} size={52} />
              {choice === avatar.id && <span aria-hidden="true" className="avatar-choice-check"><Check className="size-3" strokeWidth={3} /></span>}
            </button>
          ))}
        </div>
        <p role="status" aria-live="polite" className="mt-4 min-h-5 text-[0.875rem]">
          {state === "saving" ? "Saving…" : state === "account" ? "Saved to your account." : state === "device" ? "Saved on this device. Your account couldn't be updated right now." : state === "error" ? "That avatar couldn't be saved. Try again." : ""}
        </p>
        <div className="mt-3 flex flex-wrap justify-end gap-3">
          <button type="button" onClick={onClose} disabled={state === "saving"} className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong px-4 font-medium hover:bg-surface-muted">{state === "account" || state === "device" ? "Done" : "Cancel"}</button>
          <button type="button" onClick={save} disabled={state === "saving"} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85 disabled:opacity-45">{state === "saving" ? "Saving…" : "Save avatar"}</button>
        </div>
      </div>
    </>
  );
}
