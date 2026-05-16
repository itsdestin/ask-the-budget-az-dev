// ArmsHips — P3f. Hands on hips (confident, post-answer success pose —
// "I've got this"). Arm set regenerated to match the #arms-hips symbol in the
// committed reference mockup. Conforms to the 10px sprite grid; upper arms
// hang from the shoulder line y=210, forearms angle inward and the hands rest
// against the torso edges (torso x=80..160).
export default function ArmsHips() {
  return (
    <g>
      {/* ── Left upper arm ── hangs from the shoulder line to the elbow */}
      <rect fill="var(--mascot-suit)" x={60} y={210} width={20} height={40} />
      <rect fill="var(--mascot-suit-hi)" x={60} y={210} width={10} height={30} />

      {/* ── Right upper arm ── mirror of the left */}
      <rect fill="var(--mascot-suit)" x={160} y={210} width={20} height={40} />
      <rect fill="var(--mascot-suit-hi)" x={170} y={210} width={10} height={30} />

      {/* ── Forearms ── angle inward from the elbow toward the hips */}
      <rect fill="var(--mascot-suit)" x={70} y={250} width={30} height={20} />
      <rect fill="var(--mascot-suit)" x={140} y={250} width={30} height={20} />
      <rect fill="var(--mascot-suit-shadow)" x={70} y={260} width={30} height={10} />
      <rect fill="var(--mascot-suit-shadow)" x={140} y={260} width={30} height={10} />

      {/* ── Hands on hips ── skin resting against the torso edges */}
      <rect fill="var(--mascot-skin)" x={80} y={250} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={80} y={260} width={20} height={10} />
      <rect fill="var(--mascot-skin)" x={140} y={250} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={140} y={260} width={20} height={10} />
    </g>
  );
}
