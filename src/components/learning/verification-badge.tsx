import { CircleDashed, ListChecks, ServerCog } from "lucide-react";
import { verificationCopy, type VerificationMode } from "@/lib/learning/verification";

const looks: Record<VerificationMode, { icon: typeof ServerCog; className: string }> = {
  server_verified: { icon: ServerCog, className: "border-success/30 bg-success-soft text-success" },
  answer_key: { icon: ListChecks, className: "border-border-strong bg-surface text-foreground" },
  practice_only: { icon: CircleDashed, className: "border-border bg-surface-muted text-secondary" },
};

/** One badge for how a lesson is checked. Wording comes from the shared verification copy. */
export function VerificationBadge({ mode, prefix, className = "" }: { mode: VerificationMode; prefix?: string; className?: string }) {
  const { icon: Icon, className: tone } = looks[mode];
  return (
    <span data-verification={mode} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[0.8125rem] font-medium ${tone} ${className}`}>
      <Icon aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={2} />
      {prefix ? `${prefix} ` : ""}{verificationCopy[mode].label}
    </span>
  );
}
