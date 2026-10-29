/**
 * Vertical light streaks behind the hero, resting on the showcase window's top edge.
 * Bars come from a fixed seed, so server and client output are identical and
 * nothing random runs at render time. Pure CSS; the styling lives in globals.css.
 */

type Bar = { left: number; width: number; height: number; alpha: number; dense: boolean };

function seeded(seed: number) {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) % 4294967296;
    return state / 4294967296;
  };
}

function makeBars(count: number, seed: number, widths: [number, number], alphas: [number, number]): Bar[] {
  const random = seeded(seed);
  return Array.from({ length: count }, (_, index) => {
    const slot = (index + 0.5) / count;
    return {
      left: Math.round((slot + (random() - 0.5) / count) * 1000) / 10,
      width: Math.round(widths[0] + random() * (widths[1] - widths[0])),
      height: Math.round(55 + random() * 45),
      alpha: Math.round((alphas[0] + random() * (alphas[1] - alphas[0])) * 100) / 100,
      dense: index % 2 === 1,
    };
  });
}

// Three depths: wide soft beams at the back, mid beams, thin sharp ones in front (42 in total)
const layers = [
  { blur: 12, bars: makeBars(10, 11, [34, 60], [0.28, 0.5]), drift: true },
  { blur: 8, bars: makeBars(14, 23, [14, 34], [0.3, 0.55]), drift: false },
  { blur: 4, bars: makeBars(18, 37, [6, 14], [0.35, 0.7]), drift: false },
];

export function LightStreaks() {
  return (
    <div aria-hidden="true" className="streaks">
      {layers.map((layer, layerIndex) => (
        <div
          key={layerIndex}
          className={`streak-layer ${layer.drift ? "streak-drift" : ""}`}
          style={{ filter: `blur(${layer.blur}px)` }}
        >
          {layer.bars.map((bar, index) => (
            <span
              key={index}
              className="streak"
              data-dense={bar.dense ? "" : undefined}
              style={
                {
                  left: `${bar.left}%`,
                  width: `${bar.width}px`,
                  height: `${bar.height}%`,
                  marginLeft: `${-bar.width / 2}px`,
                  "--a": bar.alpha,
                } as React.CSSProperties
              }
            />
          ))}
        </div>
      ))}
    </div>
  );
}
