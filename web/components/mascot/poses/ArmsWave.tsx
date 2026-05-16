// ArmsWave — P3c. One arm raised in a friendly wave (welcome pose).
// Arm set regenerated to match the #arms-wave symbol in the committed
// reference mockup. Conforms to the 10px sprite grid; the left arm hangs
// from the shoulder line y=210, the right arm rises up beside the head with
// an open hand. The raised hand sits beside the head core block (head y=40..180).
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

      {/* ── Raised hand ── open palm beside the head */}
      <rect fill="var(--mascot-skin)" x={160} y={120} width={40} height={30} />
      <rect fill="var(--mascot-skin-shadow)" x={160} y={140} width={40} height={10} />
      {/* finger divisions suggested by two darker gaps */}
      <rect fill="var(--mascot-skin-shadow)" x={170} y={120} width={10} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={190} y={120} width={10} height={20} />
    </g>
  );
}
