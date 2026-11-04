"use client";

import { useId, useState } from "react";
import { avatarById, resolveAvatarId } from "@/lib/avatars/avatars";

const INK = "#151923";
const Eyes = ({ y = 34, gap = 6, r = 2.6 }: { y?: number; gap?: number; r?: number }) => (
  <>
    <circle cx={32 - gap} cy={y} r={r} fill="#fff" /><circle cx={32 + gap} cy={y} r={r} fill="#fff" />
    <circle cx={32 - gap + 0.5} cy={y + 0.5} r={r * 0.5} fill={INK} /><circle cx={32 + gap + 0.5} cy={y + 0.5} r={r * 0.5} fill={INK} />
  </>
);
const Smile = ({ y = 41 }: { y?: number }) => <path d={`M28 ${y}q4 3.5 8 0`} fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" />;

/** 64x64 artwork per avatar; `g` makes gradient ids unique per rendered avatar. */
const ART: Record<string, (g: string) => React.ReactNode> = {
  "orb-sunset": (g) => (<><defs><radialGradient id={g} cx="35%" cy="30%" r="80%"><stop offset="0" stopColor="#ffb27a" /><stop offset="1" stopColor="#e8743b" /></radialGradient></defs><circle cx="32" cy="34" r="19" fill={`url(#${g})`} /><ellipse cx="25" cy="25" rx="5" ry="3" fill="#fff" opacity="0.4" /><Eyes y={35} /><Smile y={42} /></>),
  "orb-aurora": (g) => (<><defs><radialGradient id={g} cx="35%" cy="30%" r="85%"><stop offset="0" stopColor="#6fd6c9" /><stop offset="1" stopColor="#4a4fc4" /></radialGradient></defs><circle cx="32" cy="34" r="19" fill={`url(#${g})`} /><path d="M50 14l1.5 3.5L55 19l-3.5 1.5L50 24l-1.5-3.5L45 19l3.5-1.5z" fill="#fff" opacity="0.9" /><Eyes y={35} /><Smile y={42} /></>),
  "orb-slate": (g) => (<><defs><radialGradient id={g} cx="35%" cy="30%" r="85%"><stop offset="0" stopColor="#8a93a6" /><stop offset="1" stopColor="#46505f" /></radialGradient></defs><circle cx="32" cy="34" r="19" fill={`url(#${g})`} /><ellipse cx="25" cy="25" rx="5" ry="3" fill="#fff" opacity="0.3" /><Eyes y={35} /><Smile y={42} /></>),
  "planet-ember": () => (<><circle cx="32" cy="33" r="16" fill="#e8743b" /><path d="M16 38c10 6 30 4 32-4" fill="none" stroke="#f6c177" strokeWidth="4" strokeLinecap="round" /><circle cx="39" cy="26" r="3" fill="#c8452f" opacity="0.5" /><Eyes y={31} gap={5} r={2.4} /><Smile y={38} /></>),
  "planet-teal": () => (<><circle cx="32" cy="33" r="16" fill="#2f9e92" /><ellipse cx="32" cy="36" rx="25" ry="7" fill="none" stroke="#b6e6df" strokeWidth="3" transform="rotate(-14 32 36)" /><circle cx="24" cy="25" r="2.5" fill="#1d6f66" opacity="0.6" /><Eyes y={31} gap={5} r={2.4} /><Smile y={38} /></>),
  "planet-coral": () => (<><circle cx="32" cy="33" r="16" fill="#d9664f" /><ellipse cx="32" cy="36" rx="25" ry="7" fill="none" stroke="#ffd0c4" strokeWidth="3" transform="rotate(12 32 36)" /><circle cx="40" cy="25" r="2.5" fill="#9c3f2b" opacity="0.5" /><Eyes y={31} gap={5} r={2.4} /><Smile y={38} /></>),
  "robot-coral": () => (<><path d="M32 12v7" stroke="#c8452f" strokeWidth="2.4" strokeLinecap="round" /><circle cx="32" cy="11" r="3" fill="#e8743b" /><rect x="15" y="19" width="34" height="30" rx="9" fill="#e5654d" /><rect x="11" y="29" width="5" height="10" rx="2.5" fill="#c8452f" /><rect x="48" y="29" width="5" height="10" rx="2.5" fill="#c8452f" /><rect x="22" y="28" width="7" height="7" rx="2" fill="#fff" /><rect x="35" y="28" width="7" height="7" rx="2" fill="#fff" /><rect x="24.5" y="30" width="3" height="3" rx="1" fill={INK} /><rect x="37.5" y="30" width="3" height="3" rx="1" fill={INK} /><path d="M26 41h12" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" /></>),
  "robot-indigo": () => (<><path d="M32 12v7" stroke="#3a3fa0" strokeWidth="2.4" strokeLinecap="round" /><circle cx="32" cy="11" r="3" fill="#6fd6c9" /><rect x="15" y="19" width="34" height="30" rx="9" fill="#5459d1" /><rect x="11" y="29" width="5" height="10" rx="2.5" fill="#3a3fa0" /><rect x="48" y="29" width="5" height="10" rx="2.5" fill="#3a3fa0" /><rect x="20" y="28" width="24" height="9" rx="4.5" fill="#1d2160" /><circle cx="27" cy="32.5" r="2.4" fill="#6fd6c9" /><circle cx="37" cy="32.5" r="2.4" fill="#6fd6c9" /><path d="M27 42h10" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" /></>),
  "fox-geo": () => (<><path d="M14 12l12 11-12 13z" fill="#e8743b" /><path d="M50 12L38 23l12 13z" fill="#e8743b" /><path d="M32 22l22 12-12 22H22L10 34z" fill="#f08a4b" /><path d="M32 40l10 16H22z" fill="#fff" opacity="0.92" /><path d="M10 34l12 22 10-16z" fill="#fff" opacity="0.18" /><circle cx="25" cy="37" r="2.4" fill={INK} /><circle cx="39" cy="37" r="2.4" fill={INK} /><path d="M29.5 47h5l-2.5 3z" fill={INK} /></>),
  "cat-geo": () => (<><path d="M15 11l11 12H13z" fill="#5d6678" /><path d="M49 11L38 23h13z" fill="#5d6678" /><rect x="13" y="20" width="38" height="31" rx="13" fill="#7a8397" /><path d="M13 36c8 4 30 4 38 0" stroke="#fff" strokeWidth="1.5" opacity="0.2" fill="none" /><circle cx="25" cy="34" r="3.2" fill="#fff" /><circle cx="39" cy="34" r="3.2" fill="#fff" /><ellipse cx="25" cy="34" rx="1.1" ry="2.4" fill={INK} /><ellipse cx="39" cy="34" rx="1.1" ry="2.4" fill={INK} /><path d="M30 42h4l-2 2.5z" fill="#ffb2a6" /><path d="M18 41l-6-1M18 44l-6 2M46 41l6-1M46 44l6 2" stroke="#fff" strokeWidth="1.2" opacity="0.6" strokeLinecap="round" /></>),
  "owl-geo": () => (<><path d="M16 14l9 8H14z" fill="#6b5bc0" /><path d="M48 14l-9 8h11z" fill="#6b5bc0" /><rect x="13" y="19" width="38" height="36" rx="16" fill="#8576d8" /><circle cx="24" cy="33" r="8" fill="#fff" /><circle cx="40" cy="33" r="8" fill="#fff" /><circle cx="25" cy="34" r="3.6" fill={INK} /><circle cx="39" cy="34" r="3.6" fill={INK} /><path d="M29 41h6l-3 5z" fill="#f6b04a" /><path d="M24 52l-3 4M32 53v4M40 52l3 4" stroke="#f6b04a" strokeWidth="2" strokeLinecap="round" /></>),
  "pixel-smile": () => (<><g fill="#f6b04a">{[[2,1],[3,1],[4,1],[5,1],[1,2],[2,2],[3,2],[4,2],[5,2],[6,2],[1,3],[2,3],[3,3],[4,3],[5,3],[6,3],[1,4],[2,4],[3,4],[4,4],[5,4],[6,4],[1,5],[2,5],[3,5],[4,5],[5,5],[6,5],[2,6],[3,6],[4,6],[5,6]].map(([x, y]) => <rect key={`${x}${y}`} x={8 + x * 6} y={8 + y * 6} width="6" height="6" />)}</g><g fill={INK}><rect x="26" y="26" width="6" height="6" /><rect x="38" y="26" width="6" height="6" /><rect x="20" y="38" width="6" height="6" /><rect x="26" y="44" width="18" height="6" /><rect x="44" y="38" width="6" height="6" /></g></>),
  "pixel-ghost": () => (<><g fill="#fff">{[[3,1],[4,1],[2,2],[3,2],[4,2],[5,2],[1,3],[2,3],[3,3],[4,3],[5,3],[6,3],[1,4],[2,4],[3,4],[4,4],[5,4],[6,4],[1,5],[2,5],[3,5],[4,5],[5,5],[6,5],[1,6],[3,6],[4,6],[6,6]].map(([x, y]) => <rect key={`${x}${y}`} x={8 + x * 6} y={8 + y * 6} width="6" height="6" />)}</g><g fill="#4a4fc4"><rect x="26" y="26" width="6" height="8" /><rect x="38" y="26" width="6" height="8" /><rect x="29" y="40" width="12" height="4" /></g></>),
  "rocket-amber": () => (<><path d="M32 8c9 6 12 16 11 28H21C20 24 23 14 32 8z" fill="#fff" /><path d="M32 8c5 3.5 8 8 9.5 14H22.5C24 16 27 11.5 32 8z" fill="#e8743b" /><circle cx="32" cy="27" r="5" fill="#2f9e92" /><circle cx="30.5" cy="25.5" r="1.4" fill="#fff" opacity="0.8" /><path d="M21 31l-7 9 7-1zM43 31l7 9-7-1z" fill="#f6b04a" /><path d="M27 38h10l-5 13z" fill="#f6b04a" /><path d="M29.5 38h5l-2.5 8z" fill="#fff3d0" /></>),
};

/** Only HTTPS images from the backend are shown, without sending a referrer; anything else is ignored. */
const safeSrc = (src: string | null | undefined) => (src && /^https:\/\//i.test(src) ? src : null);

/**
 * One avatar everywhere (navbar, account, leaderboard, completion). Shows the chosen avatar if it
 * is on the allowlist, otherwise a stable default from `seed`. Never initials. Alt text is only
 * "Avatar".
 */
export function Avatar({ avatarId, seed, src, size = 40, loading = false, decorative = false, className = "" }: {
  avatarId?: string | null;
  /** A stable, non-personal id (account or row id) for the default avatar. */
  seed: string;
  /** Optional remote image (leaderboard); falls back to the drawn avatar on any error. */
  src?: string | null;
  size?: number;
  loading?: boolean;
  /** Hide from assistive tech where the name is already next to it (for example "Account"). */
  decorative?: boolean;
  className?: string;
}) {
  const [broken, setBroken] = useState(false);
  const gradient = useId();
  const bgId = `${gradient}-bg`;
  if (loading) return <span aria-hidden="true" className={`skeleton inline-block shrink-0 rounded-full ${className}`} style={{ width: size, height: size }} />;
  const remote = safeSrc(src);
  if (remote && !broken) {
    // eslint-disable-next-line @next/next/no-img-element -- untrusted remote avatars are loaded as-is, never optimized or proxied
    return <img src={remote} alt={decorative ? "" : "Avatar"} width={size} height={size} referrerPolicy="no-referrer" loading="lazy" decoding="async" onError={() => setBroken(true)} className={`shrink-0 rounded-full object-cover ${className}`} style={{ width: size, height: size }} />;
  }
  const id = resolveAvatarId(avatarId, seed);
  const design = avatarById(id)!;
  return (
    <svg role={decorative ? undefined : "img"} aria-label={decorative ? undefined : "Avatar"} aria-hidden={decorative || undefined} viewBox="0 0 64 64" width={size} height={size} className={`shrink-0 rounded-full ${className}`} data-avatar={design.id}>
      <defs>
        <linearGradient id={bgId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={design.bg[0]} />
          <stop offset="1" stopColor={design.bg[1]} />
        </linearGradient>
      </defs>
      <rect width="64" height="64" fill={`url(#${bgId})`} />
      {ART[id](`${gradient}-art`)}
    </svg>
  );
}
