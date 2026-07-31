// ArmsClasped — P3b. Hands clasped together in front of the waist.
// This is the DEFAULT IDLE POSE. Arm set regenerated to match the
// #arms-clasped symbol in the committed reference mockup. Conforms to the
// 10px sprite grid; upper arms hang from the shoulder line y=210, forearms
// angle inward and the hands meet on the torso centerline x=120.
export default function ArmsClasped() {
  return (
    <g>
      {/* ── Left upper arm ── hangs from the shoulder line */}
      <rect fill="var(--mascot-suit)" x={60} y={210} width={20} height={40} />
      <rect fill="var(--mascot-suit-hi)" x={60} y={210} width={10} height={30} />

      {/* ── Right upper arm ── mirror of the left */}
      <rect fill="var(--mascot-suit)" x={160} y={210} width={20} height={40} />
      <rect fill="var(--mascot-suit-hi)" x={170} y={210} width={10} height={30} />

      {/* ── Forearms ── angle inward toward the waist, meeting at center */}
      <rect fill="var(--mascot-suit)" x={70} y={240} width={50} height={20} />
      <rect fill="var(--mascot-suit)" x={120} y={240} width={50} height={20} />
      {/* under-crease shadow along the bottom of each forearm */}
      <rect fill="var(--mascot-suit-shadow)" x={70} y={250} width={50} height={10} />
      <rect fill="var(--mascot-suit-shadow)" x={120} y={250} width={50} height={10} />

      {/* ── Clasped hands ── meeting on the torso centerline */}
      <rect fill="var(--mascot-skin)" x={100} y={250} width={40} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={100} y={260} width={40} height={10} />
      {/* the seam where the two hands meet */}
      <rect fill="var(--mascot-skin-shadow)" x={110} y={250} width={10} height={20} />
    </g>
  );
}
