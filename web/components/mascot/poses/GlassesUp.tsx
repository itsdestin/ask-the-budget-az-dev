// GlassesUp — a small overlay drawing the glasses shifted UP one 10px cell.
// Rendered additively over the body during the ~700ms push-glasses idle moment
// (Mascot.tsx) so the glasses visibly "ride up" while the hand reaches them.
//
// Registration: MascotBody draws the resting glasses with the left lens at
// x=60..100 y=120..160, the right lens at x=140..180 y=120..160, and the bridge
// at x=100..140 y=130. This overlay is that exact frame translated up by one
// 10px grid cell (every y minus 10), matching the #glasses-up symbol in the
// reference mockup (specs/assets/2026-05-15-mascot-reference/idle-moments.html).
// hex → var(--mascot-*) per the SPRITE SYSTEM palette in MascotBody.tsx.
//
// Blanking strategy: before drawing the raised frame we paint var(--mascot-skin)
// rects over the RESTING frame footprint so the doubled-glasses artifact is
// eliminated. Blanking covers only the frame rects (top/bottom bars + side
// strips + bridge). The pupils (data-mascot-eye, x=70 y=130 w=20 h=20 and
// x=150 y=130 w=20 h=20) sit INSIDE each lens interior and are deliberately
// NOT blanked — when the frame rides up the eyes stay put, which is exactly
// the "glasses pushed up off the eyes" read. The frame geometry is unchanged
// by the Take-3 redesign (thin hollow frame, same footprint), so this overlay
// still lines up without coordinate updates.
//
// Resting frame bounding box blanked: x=60 y=120 to x=180 y=160.
// Blanking is limited to the frame footprint; face skin and the pupils are
// intentionally untouched.
export default function GlassesUp() {
  return (
    <g>
      {/* ── Blank resting glasses frame — paint skin over the frame rects so
            the body's resting glasses don't show through the raised position.
            Covers: top bars (y=120), bottom bars (y=150), side strips and
            eye-row interiors (y=130..150 for each lens), and bridge (y=130).
            We blank the full width of each lens (x=60..100, x=140..180) plus
            the bridge (x=100..140) at each relevant row rather than individual
            side-strip rects — simpler and still limited to the frame footprint. ── */}
      {/* left lens — top bar */}
      <rect fill="var(--mascot-skin)" x={60} y={120} width={40} height={10} />
      {/* left lens — interior rows (side strips + eye row) */}
      <rect fill="var(--mascot-skin)" x={60} y={130} width={10} height={20} />
      <rect fill="var(--mascot-skin)" x={90} y={130} width={10} height={20} />
      {/* eye row interior (x=70..90) is already skin from head — no extra rect needed */}
      {/* left lens — bottom bar */}
      <rect fill="var(--mascot-skin)" x={60} y={150} width={40} height={10} />
      {/* bridge */}
      <rect fill="var(--mascot-skin)" x={100} y={130} width={40} height={10} />
      {/* right lens — top bar */}
      <rect fill="var(--mascot-skin)" x={140} y={120} width={40} height={10} />
      {/* right lens — interior rows (side strips + eye row) */}
      <rect fill="var(--mascot-skin)" x={140} y={130} width={10} height={20} />
      <rect fill="var(--mascot-skin)" x={170} y={130} width={10} height={20} />
      {/* right lens — bottom bar */}
      <rect fill="var(--mascot-skin)" x={140} y={150} width={40} height={10} />

      {/* ── Raised glasses frame — resting frame translated up by 10px ── */}
      {/* left lens */}
      <rect fill="var(--mascot-suit)" x={60} y={110} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={60} y={140} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={60} y={120} width={10} height={20} />
      <rect fill="var(--mascot-suit)" x={90} y={120} width={10} height={20} />
      {/* right lens */}
      <rect fill="var(--mascot-suit)" x={140} y={110} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={140} y={140} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={140} y={120} width={10} height={20} />
      <rect fill="var(--mascot-suit)" x={170} y={120} width={10} height={20} />
      {/* bridge */}
      <rect fill="var(--mascot-suit)" x={100} y={120} width={40} height={10} />
    </g>
  );
}
