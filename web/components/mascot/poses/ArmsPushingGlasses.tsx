// ArmsPushingGlasses — idle "push-up-glasses" arm set. The left arm hangs
// straight down at the side; the right arm bends UP so the hand reaches the
// glasses on the head. Used only for the ~700ms push-glasses idle moment
// (Mascot.tsx), swapped in over whatever the resting pose was.
//
// Regenerated from the #arms-pushing symbol in the committed reference mockup
// (specs/assets/2026-05-15-mascot-reference/idle-moments.html). Conforms to the
// 10px sprite grid; hex → var(--mascot-*) per the SPRITE SYSTEM palette in
// MascotBody.tsx. Arms render ON TOP of the body, 10px torso overlap is the seam.
export default function ArmsPushingGlasses() {
  return (
    <g>
      {/* ── Left arm ── hanging straight down at the side (mirrors ArmsSides) */}
      <rect fill="var(--mascot-suit)" x={60} y={210} width={20} height={60} />
      <rect fill="var(--mascot-suit-hi)" x={60} y={210} width={10} height={40} />
      <rect fill="var(--mascot-skin)" x={60} y={270} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={60} y={280} width={20} height={10} />

      {/* ── Right arm raised to the glasses ── */}
      {/* shoulder stub at the shoulder line before the arm bends upward */}
      <rect fill="var(--mascot-suit)" x={160} y={210} width={20} height={20} />
      <rect fill="var(--mascot-suit-hi)" x={170} y={210} width={10} height={20} />
      {/* forearm running up beside the head toward the glasses */}
      <rect fill="var(--mascot-suit)" x={150} y={160} width={20} height={60} />
      {/* vertical SIDE highlight strip along the outer edge of the raised arm (x=150, matching the outer-edge highlight convention in ArmsSides.tsx) */}
      <rect fill="var(--mascot-suit-hi)" x={150} y={160} width={10} height={50} />
      {/* hand reaching the glasses — sits over the right lens / bridge region */}
      <rect fill="var(--mascot-skin)" x={140} y={120} width={40} height={40} />
      <rect fill="var(--mascot-skin-shadow)" x={140} y={150} width={40} height={10} />
    </g>
  );
}
