/**
 * Background panel behind the hero device: a warm mesh gradient, faint execution-trace
 * line work and soft light streaks. Pure CSS/SVG, no photography. Decorative.
 */

// Vertical light bars: fixed values, so server and client render identically.
const bars = [
  [6, 54, 0.22], [11, 30, 0.14], [17, 70, 0.2], [24, 42, 0.16], [31, 60, 0.24], [38, 34, 0.12],
  [46, 66, 0.2], [55, 40, 0.15], [62, 72, 0.22], [69, 36, 0.13], [76, 58, 0.21], [83, 46, 0.16],
  [90, 64, 0.2], [95, 32, 0.12],
] as const;

export function DevicePanel() {
  return (
    <div aria-hidden="true" className="device-panel">
      <div className="device-mesh" />
      <svg className="absolute inset-0 h-full w-full" viewBox="0 0 1200 700" preserveAspectRatio="xMidYMid slice">
        <g fill="none" stroke="#ffffff" strokeOpacity="0.22" strokeWidth="1.5" strokeLinecap="round">
          <path d="M40 140 H260 Q280 140 280 160 V300 Q280 320 300 320 H520" />
          <path d="M520 320 H690 Q710 320 710 300 V180 Q710 160 730 160 H1160" />
          <path d="M710 320 V470 Q710 490 730 490 H980 Q1000 490 1000 510 V640" />
          <path d="M40 560 H180 Q200 560 200 540 V420 Q200 400 220 400 H420" />
        </g>
        <g fill="#ffffff" fillOpacity="0.24">
          {[[280, 160], [520, 320], [710, 320], [730, 160], [1000, 510], [200, 420], [420, 400]].map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="4.5" />
          ))}
        </g>
      </svg>
      <div className="absolute inset-0 [mask-image:linear-gradient(to_bottom,black,transparent_85%)]">
        {bars.map(([left, height, alpha]) => (
          <span
            key={left}
            className="absolute top-0 w-[3%] rounded-b-full"
            style={{
              left: `${left}%`,
              height: `${height}%`,
              background: `linear-gradient(to bottom, rgba(255,255,255,${alpha}), transparent)`,
            }}
          />
        ))}
      </div>
    </div>
  );
}
