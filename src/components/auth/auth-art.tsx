import { PauseOffscreen } from "./pause-offscreen";

/**
 * Original art for the sign-in pages: a warm mesh, a trace path that lights up node by
 * node, and a small lesson window. The code is an excerpt from the real first lesson
 * (backend catalog, "fastapi-payload-mismatch" 1.0.0) and is labelled as an example.
 * Decorative: hidden from assistive tech. Motion is transform/opacity only, pauses
 * off-screen, and is static with reduced motion.
 */
const code = ["payload = {", '    "title": note.title,', '    "body": note.content,', "}", 'client.post("/notes", json=payload)'];
const PATH = "M40 90 C 160 90, 170 210, 290 210 S 420 330, 520 330 S 560 470, 470 520";
const nodes = [
  [40, 90],
  [290, 210],
  [520, 330],
  [470, 520],
] as const;
const streaks = [
  [8, 34, 0.5], [16, 18, 0.42], [27, 46, 0.36], [39, 22, 0.5], [52, 38, 0.32], [63, 16, 0.46], [74, 30, 0.4], [86, 20, 0.5], [93, 40, 0.3],
] as const;

export function AuthArt() {
  return (
    <div aria-hidden="true" className="auth-art relative h-full min-h-[560px] overflow-hidden rounded-[28px]">
      <PauseOffscreen />
      <div className="auth-mesh absolute inset-[-10%]" />
      <div className="absolute inset-x-0 bottom-0 h-[46%] [mask-image:linear-gradient(to_top,black,transparent)]">
        {streaks.map(([left, width, alpha], index) => (
          <span key={index} className="auth-streak absolute bottom-0" style={{ left: `${left}%`, width, "--w": `${width}px`, height: `${55 + ((index * 17) % 40)}%`, "--a": alpha, "--i": index } as React.CSSProperties} />
        ))}
      </div>

      <svg viewBox="0 0 600 640" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 size-full">
        <defs>
          <clipPath id="auth-draw"><rect className="auth-draw" x="0" y="0" width="600" height="640" /></clipPath>
        </defs>
        <path d={PATH} fill="none" stroke="rgba(255,255,255,0.35)" strokeWidth="1.5" strokeDasharray="3 7" />
        <path d={PATH} fill="none" stroke="rgba(255,255,255,0.9)" strokeWidth="2" clipPath="url(#auth-draw)" />
        {nodes.map(([x, y], index) => (
          <g key={index}>
            <circle cx={x} cy={y} r="9" fill="rgba(255,255,255,0.28)" />
            <circle cx={x} cy={y} r="4.5" fill="#fff" />
            <circle className="auth-pulse" cx={x} cy={y} r="14" fill="none" stroke="#fff" strokeWidth="1.5" style={{ "--i": index } as React.CSSProperties} />
          </g>
        ))}
      </svg>

      <div className="auth-window absolute top-1/2 left-1/2 w-[min(84%,400px)] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border border-white/70 bg-white/95 shadow-[0_30px_60px_-30px_rgba(90,30,10,0.55)]">
        <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
          <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-[#ff5f57]" /><span className="size-2.5 rounded-full bg-[#febc2e]" /><span className="size-2.5 rounded-full bg-[#28c840]" /></span>
          <span className="truncate font-mono text-[0.6875rem] text-secondary">request_builder.py</span>
          <span className="shrink-0 rounded-full border border-border px-2 py-0.5 font-mono text-[0.625rem] tracking-[0.04em] text-secondary uppercase">Example</span>
        </div>
        <pre className="relative py-3 font-mono text-[0.75rem] leading-[1.7] text-foreground">
          {code.map((line, index) => (
            <span key={index} className="relative block px-4">
              <span className="auth-hl absolute inset-0 bg-primary-soft shadow-[inset_2px_0_0_var(--primary)]" data-focus={index === 2 ? "" : undefined} style={{ "--i": index } as React.CSSProperties} />
              <span className="relative"><span className="mr-3 inline-block w-3 text-right text-tertiary">{index + 1}</span>{line}</span>
            </span>
          ))}
        </pre>
        <p className="border-t border-border px-4 py-2.5 text-[0.75rem] text-secondary">From lesson 1: what happens to <span className="font-mono">&quot;body&quot;</span>?</p>
      </div>
    </div>
  );
}
