import type { CSSProperties, ReactNode } from "react";

/**
 * Small charts for the account overview. They draw only numbers that come from the learner's own
 * saved history. Each chart has a text summary for screen readers; the drawing is aria-hidden.
 */

export function ChartCard({ title, note, children, className = "" }: { title: string; note?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section aria-label={title} className={`dash-card ${className}`}>
      <header className="dash-card-head">
        <h3>{title}</h3>
        {note && <p>{note}</p>}
      </header>
      {children}
    </section>
  );
}

/** A ring showing `value` of `total`. */
export function Donut({ id, value, total, centre, caption }: { id: string; value: number; total: number; centre: string; caption: string }) {
  const share = total > 0 ? Math.min(1, value / total) : 0;
  return (
    <div className="donut" role="img" aria-label={`${caption}: ${centre}`}>
      <svg aria-hidden="true" viewBox="0 0 120 120">
        <defs>
          <linearGradient id={`donut-${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#ffb27a" />
            <stop offset="100%" stopColor="#ff7a2e" />
          </linearGradient>
        </defs>
        <circle cx="60" cy="60" r="48" fill="none" stroke="rgba(21,25,35,0.08)" strokeWidth="12" />
        <circle className="donut-arc" cx="60" cy="60" r="48" fill="none" stroke={`url(#donut-${id})`} strokeWidth="12" strokeLinecap="round" pathLength={1} strokeDasharray={`${share} 1`} transform="rotate(-90 60 60)" style={{ "--share": share } as CSSProperties} />
      </svg>
      <div aria-hidden="true" className="donut-centre"><strong>{centre}</strong><span>{caption}</span></div>
    </div>
  );
}

export type BarItem = { label: string; a: number; b?: number };

/** Paired columns: `a` in orange, `b` (optional) in graphite. */
export function PairedBars({ items, aLabel, bLabel }: { items: BarItem[]; aLabel: string; bLabel: string }) {
  const max = Math.max(1, ...items.flatMap((item) => [item.a, item.b ?? 0]));
  return (
    <div>
      <ul className="bars" style={{ "--cols": items.length } as CSSProperties}>
        {items.map((item, index) => (
          <li key={item.label} style={{ "--k": index } as CSSProperties}>
            <span className="sr-only">{item.label}: {item.a} {aLabel.toLowerCase()}, {item.b ?? 0} {bLabel.toLowerCase()}.</span>
            <div aria-hidden="true" className="bars-plot">
              <span className="bar bar-a" style={{ "--h": item.a / max } as CSSProperties}><em>{item.a}</em></span>
              <span className="bar bar-b" style={{ "--h": (item.b ?? 0) / max } as CSSProperties}><em>{item.b ?? 0}</em></span>
            </div>
            <span aria-hidden="true" className="bars-label" title={item.label}>{item.label}</span>
          </li>
        ))}
      </ul>
      <p aria-hidden="true" className="legend"><span><i className="dot-a" />{aLabel}</span><span><i className="dot-b" />{bLabel}</span></p>
    </div>
  );
}

export type DayItem = { key: string; day: number; weekday: string; count: number };

/** One slim column per day. */
export function DayBars({ days, unit }: { days: DayItem[]; unit: string }) {
  const max = Math.max(1, ...days.map((day) => day.count));
  const total = days.reduce((sum, day) => sum + day.count, 0);
  return (
    <div>
      <p className="sr-only">{total} {unit} in the last {days.length} days.</p>
      <ul aria-hidden="true" className="days" style={{ "--cols": days.length } as CSSProperties}>
        {days.map((day, index) => (
          <li key={day.key} title={`${day.weekday} ${day.day}: ${day.count} ${unit}`} data-today={index === days.length - 1 ? "" : undefined} style={{ "--k": index } as CSSProperties}>
            <span className="day-col"><span className="day-bar" data-zero={day.count === 0 ? "" : undefined} style={{ "--h": day.count / max } as CSSProperties} /></span>
            <span className="day-label">{index % 2 === 0 || index === days.length - 1 ? day.day : ""}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A thin horizontal meter with a text value beside it. */
export function Meter({ label, value, total, status }: { label: string; value: number; total: number; status?: ReactNode }) {
  const share = total > 0 ? Math.min(1, value / total) : 0;
  return (
    <li className="meter">
      <div className="meter-row"><span className="meter-label">{label}</span>{status}</div>
      <span aria-hidden="true" className="meter-track"><span className="meter-fill" style={{ "--share": share } as CSSProperties} /></span>
    </li>
  );
}
