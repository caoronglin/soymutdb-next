/**
 * DnaBackground — pure-CSS animated DNA helix decoration for the hero.
 *
 * Uses positioned divs with staggered animation delays to create a
 * double-helix / molecular-grid effect. Extremely cheap (no canvas/WebGL,
 * no JS, transform+opacity only). Auto-disabled for reduced-motion users.
 */
export function DnaBackground() {
  // Deterministic positions so the pattern is stable across renders
  const strands = [
    { left: "8%", height: "60%", top: "20%", delay: "0s", dur: "5s" },
    { left: "22%", height: "80%", top: "10%", delay: "0.8s", dur: "6s" },
    { left: "45%", height: "50%", top: "25%", delay: "1.5s", dur: "5.5s" },
    { left: "68%", height: "70%", top: "15%", delay: "0.3s", dur: "6.5s" },
    { left: "88%", height: "55%", top: "22%", delay: "2s", dur: "5s" },
    { left: "95%", height: "45%", top: "28%", delay: "1.2s", dur: "7s" },
  ];

  // Horizontal "rungs" connecting strands (abstract base pairs)
  const rungs = Array.from({ length: 24 }, (_, i) => {
    const seed = i * 137.508; // golden-angle distribution
    return {
      top: `${5 + (i * 3.8)}%`,
      left: `${5 + ((seed * 7) % 90)}%`,
      width: `${20 + ((seed * 13) % 50)}px`,
      delay: `${(i * 0.25) % 4}s`,
      dur: `${4 + ((i * 0.7) % 3)}s`,
    };
  });

  // Floating "atom" dots
  const dots = Array.from({ length: 18 }, (_, i) => {
    const seed = i * 217.31;
    return {
      top: `${5 + ((seed * 11) % 85)}%`,
      left: `${3 + ((seed * 17) % 92)}%`,
      size: 3 + ((seed * 3) % 5),
      delay: `${(i * 0.4) % 3}s`,
      dur: `${3 + ((i * 0.5) % 4)}s`,
    };
  });

  return (
    <div className="dna-bg" aria-hidden="true">
      {/* Soft radial glow behind hero */}
      <div
        className="absolute -top-1/4 right-0 h-[600px] w-[600px] rounded-full opacity-20 dark:opacity-15"
        style={{
          background: "radial-gradient(circle, var(--primary) 0%, transparent 70%)",
          filter: "blur(80px)",
        }}
      />
      <div
        className="absolute bottom-0 left-1/4 h-[400px] w-[400px] rounded-full opacity-10 dark:opacity-8"
        style={{
          background: "radial-gradient(circle, var(--primary-gradient-start) 0%, transparent 70%)",
          filter: "blur(60px)",
        }}
      />

      {/* Vertical strands */}
      {strands.map((s, i) => (
        <div
          key={`s-${i}`}
          className="dna-strand"
          style={{
            left: s.left,
            height: s.height,
            top: s.top,
            animationDelay: s.delay,
            animationDuration: s.dur,
          }}
        />
      ))}

      {/* Horizontal rungs (base pairs) */}
      {rungs.map((r, i) => (
        <div
          key={`r-${i}`}
          className="dna-rung"
          style={{
            top: r.top,
            left: r.left,
            width: r.width,
            animationDelay: r.delay,
            animationDuration: r.dur,
          }}
        />
      ))}

      {/* Floating dots */}
      {dots.map((d, i) => (
        <div
          key={`d-${i}`}
          className="dna-dot"
          style={{
            top: d.top,
            left: d.left,
            width: `${d.size}px`,
            height: `${d.size}px`,
            animationDelay: d.delay,
            animationDuration: d.dur,
          }}
        />
      ))}
    </div>
  );
}
