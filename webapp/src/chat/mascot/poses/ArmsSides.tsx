// ArmsSides — P3a. Arms hanging straight down at the sides (resting / neutral).
// Arm set regenerated to match the #arms-sides symbol in the committed
// reference mockup. Conforms to the 10px sprite grid; both arm stubs hang
// from the shoulder line y=210, outside the torso (see MascotBody SPRITE SYSTEM).
export default function ArmsSides() {
  return (
    <g>
      {/* ── Left arm ── 20w sleeve stub hanging from the shoulder line */}
      <rect fill="var(--mascot-suit)" x={60} y={210} width={20} height={60} />
      {/* highlight strip down the outer edge */}
      <rect fill="var(--mascot-suit-hi)" x={60} y={210} width={10} height={40} />
      {/* hand at the cuff */}
      <rect fill="var(--mascot-skin)" x={60} y={270} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={60} y={280} width={20} height={10} />

      {/* ── Right arm ── mirror of the left */}
      <rect fill="var(--mascot-suit)" x={160} y={210} width={20} height={60} />
      {/* highlight strip down the outer edge */}
      <rect fill="var(--mascot-suit-hi)" x={170} y={210} width={10} height={40} />
      {/* hand at the cuff */}
      <rect fill="var(--mascot-skin)" x={160} y={270} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={160} y={280} width={20} height={10} />
    </g>
  );
}
