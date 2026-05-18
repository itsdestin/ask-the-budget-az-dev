// ArmsWave — P3c. One arm raised in a friendly wave (welcome pose).
// Arm set regenerated to match the #arms-wave symbol in the committed
// reference mockup. Conforms to the 10px sprite grid; the left arm hangs
// from the shoulder line y=210, the right arm rises up beside the head with
// an open waving hand. The raised hand sits in front of the head core block
// (head y=40..180) and carries a skin-shadow edge so it reads against the face.
export default function ArmsWave() {
  return (
    <g>
      {/* ── Left arm ── hanging straight down at the side */}
      <rect fill="var(--mascot-suit)" x={60} y={210} width={20} height={60} />
      <rect fill="var(--mascot-suit-hi)" x={60} y={210} width={10} height={40} />
      <rect fill="var(--mascot-skin)" x={60} y={270} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={60} y={280} width={20} height={10} />

      {/* ── Right arm raised ── */}
      {/* shoulder stub at the shoulder line before the arm bends upward */}
      <rect fill="var(--mascot-suit)" x={160} y={210} width={20} height={20} />
      <rect fill="var(--mascot-suit-hi)" x={170} y={210} width={10} height={20} />
      {/* upper arm running up beside the head */}
      <rect fill="var(--mascot-suit)" x={170} y={160} width={20} height={60} />
      {/* highlight is a vertical SIDE strip down the inner/left half of the raised arm (same x, half the width) — not a top strip */}
      <rect fill="var(--mascot-suit-hi)" x={170} y={160} width={10} height={60} />
      {/* cuff at the wrist */}
      <rect fill="var(--mascot-suit)" x={160} y={150} width={30} height={10} />

      {/* ── Raised hand ── open waving palm above the wrist cuff. Clean
            pixel-art proportions: a 3×3-cell palm block (30×30, matching the
            ~2-3 cell hand scale of ArmsClasped/ArmsHips) with three 10px
            finger nubs on top. The hand sits in front of the head, so a
            --mascot-skin-shadow edge runs down the LEFT side (the side facing
            the face) plus along the bottom — this separates the hand
            silhouette from the skin-colored face behind it. ── */}
      {/* finger nubs — three 10px-wide nubs rising off the top of the palm */}
      <rect fill="var(--mascot-skin)" x={160} y={110} width={10} height={10} />
      <rect fill="var(--mascot-skin)" x={170} y={110} width={10} height={10} />
      <rect fill="var(--mascot-skin)" x={180} y={110} width={10} height={10} />
      {/* finger separation gaps — thin skin-shadow lines between the nubs */}
      <rect fill="var(--mascot-skin-shadow)" x={169} y={110} width={2} height={10} />
      <rect fill="var(--mascot-skin-shadow)" x={179} y={110} width={2} height={10} />
      {/* palm block */}
      <rect fill="var(--mascot-skin)" x={160} y={120} width={30} height={30} />
      {/* left edge — skin-shadow outline on the side facing the face */}
      <rect fill="var(--mascot-skin-shadow)" x={160} y={110} width={4} height={40} />
      {/* bottom edge — skin-shadow crease where the palm meets the cuff */}
      <rect fill="var(--mascot-skin-shadow)" x={160} y={144} width={30} height={6} />
    </g>
  );
}
