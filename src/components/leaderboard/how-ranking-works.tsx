/** A small disclosure under the heading: the three rules of the board, in plain words. */
export function HowRankingWorks() {
  return (
    <details className="acct-details group enter mt-3 max-w-[40rem] text-[0.9375rem]" style={{ "--d": "320ms" } as React.CSSProperties}>
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center font-medium underline underline-offset-4">How ranking works</summary>
      <ul className="mt-2 grid gap-1.5 text-secondary">
        <li>Only problems checked by Trace&apos;s server count. Attempts, drafts and unfinished work don&apos;t.</li>
        <li>Finishing the same problem again counts once.</li>
        <li>People with the same number share a rank.</li>
        <li>Lessons made by AI for you don&apos;t count. They&apos;re practice, not server-checked.</li>
      </ul>
    </details>
  );
}
