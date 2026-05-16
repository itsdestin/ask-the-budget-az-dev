// ArmsCrossed — P3d. Arms crossed over the chest (refusal pose —
// "I don't have a source for that"). Arm set regenerated to match the
// #arms-crossed symbol in the committed reference mockup. Conforms to the
// 10px sprite grid; short shoulder stubs drop from the shoulder line y=210,
// then two stacked forearm bars cross the torso (torso x=80..160).
export default function ArmsCrossed() {
  return (
    <g>
      {/* ── Shoulder stubs ── short drop before the arms cross */}
      <rect fill="var(--mascot-suit)" x={60} y={210} width={20} height={20} />
      <rect fill="var(--mascot-suit)" x={160} y={210} width={20} height={20} />
      <rect fill="var(--mascot-suit-hi)" x={60} y={210} width={10} height={20} />
      <rect fill="var(--mascot-suit-hi)" x={170} y={210} width={10} height={20} />

      {/* ── Lower forearm ── the left arm crosses underneath */}
      <rect fill="var(--mascot-suit)" x={70} y={230} width={100} height={20} />
      <rect fill="var(--mascot-suit-shadow)" x={70} y={240} width={100} height={10} />

      {/* ── Upper forearm ── the right arm crosses over the top */}
      <rect fill="var(--mascot-suit)" x={70} y={210} width={100} height={20} />
      <rect fill="var(--mascot-suit-hi)" x={70} y={210} width={100} height={10} />

      {/* ── Hands ── tucked at the opposite elbows */}
      {/* left hand tucked under the right elbow (on the upper bar) */}
      <rect fill="var(--mascot-skin)" x={160} y={210} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={160} y={220} width={20} height={10} />
      {/* right hand tucked under the left elbow (on the lower bar) */}
      <rect fill="var(--mascot-skin)" x={60} y={230} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={60} y={240} width={20} height={10} />
    </g>
  );
}
