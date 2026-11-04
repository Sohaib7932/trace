import { LightStreaks } from "@/components/marketing/light-streaks";

/**
 * The landing page's look in a lighter form for app pages: a warm wash at the top, a short band
 * of faint vertical light streaks. `calm` (lesson workspaces) keeps
 * only the wash. Decorative and static (the streaks drift very slowly with motion allowed).
 */
export function AmbientPage({ children, calm = false, plain = false }: { children: React.ReactNode; calm?: boolean; plain?: boolean }) {
  if (plain) return <div className="ambient-page">{children}</div>;
  return (
    <div className="ambient-page" data-calm={calm ? "" : undefined}>
      <div aria-hidden="true" className="ambient-backdrop">
        <div className="ambient-wash" />
        {!calm && (
          <>
            <LightStreaks variant="ambient" />
          </>
        )}
      </div>
      {children}
    </div>
  );
}
