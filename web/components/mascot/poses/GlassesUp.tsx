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
export default function GlassesUp() {
  return (
    <g>
      {/* ── Left lens — body glasses frame shifted up 10px ── */}
      <rect fill="var(--mascot-suit)" x={60} y={110} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={60} y={140} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={60} y={120} width={10} height={20} />
      <rect fill="var(--mascot-suit)" x={90} y={120} width={10} height={20} />
      {/* ── Right lens ── */}
      <rect fill="var(--mascot-suit)" x={140} y={110} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={140} y={140} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={140} y={120} width={10} height={20} />
      <rect fill="var(--mascot-suit)" x={170} y={120} width={10} height={20} />
      {/* ── Bridge ── */}
      <rect fill="var(--mascot-suit)" x={100} y={120} width={40} height={10} />
    </g>
  );
}
