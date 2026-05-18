// ArmsWave — P3c. One arm raised in a friendly wave (welcome pose).
// Conforms to the 10px sprite grid; arms attach at the shoulder line y=210.
// The left arm hangs at the side. The right arm is a low, gentle CURVE —
// a sweep of overlapping suit rects whose offsets step up-and-out (not a
// hard L), rising to an open mitten hand at about shoulder height, out
// past the head's right edge so it never covers the face.
export default function ArmsWave() {
  return (
    <g>
      {/* ── Left arm ── hanging straight down at the side */}
      <rect fill="var(--mascot-suit)" x={60} y={210} width={20} height={60} />
      <rect fill="var(--mascot-suit-hi)" x={60} y={210} width={10} height={40} />
      <rect fill="var(--mascot-skin)" x={60} y={270} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={60} y={280} width={20} height={10} />

      {/* ── Right arm — raised wave ──
            Three short overlapping segments stepped up-and-out so the
            silhouette reads as a gentle curve. Consistent limb width;
            each segment overlaps the next so there are no gaps. */}
      <rect fill="var(--mascot-suit)" x={158} y={212} width={36} height={22} />
      <rect fill="var(--mascot-suit-shadow)" x={158} y={226} width={36} height={8} />
      <rect fill="var(--mascot-suit)" x={178} y={198} width={28} height={22} />
      <rect fill="var(--mascot-suit)" x={192} y={184} width={24} height={22} />
      <rect fill="var(--mascot-suit-hi)" x={192} y={184} width={8} height={22} />

      {/* ── Raised hand ── open mitten at the top of the curve: a rounded
            finger block + a thumb nub, overlapping the forearm so it is
            firmly attached. A --mascot-skin-shadow left edge + bottom
            crease separate the hand from the head behind it. */}
      {/* rounded top row — inset so the mitten top is not a hard corner */}
      <rect fill="var(--mascot-skin)" x={194} y={158} width={18} height={6} />
      <rect fill="var(--mascot-skin-hi)" x={194} y={158} width={9} height={6} />
      {/* main finger block (all fingers merged — mitten) */}
      <rect fill="var(--mascot-skin)" x={189} y={164} width={28} height={26} />
      {/* thumb nub, lower-left */}
      <rect fill="var(--mascot-skin)" x={182} y={172} width={11} height={13} />
      {/* skin-shadow — left edge + bottom crease */}
      <rect fill="var(--mascot-skin-shadow)" x={189} y={164} width={4} height={26} />
      <rect fill="var(--mascot-skin-shadow)" x={189} y={184} width={28} height={6} />
    </g>
  );
}
