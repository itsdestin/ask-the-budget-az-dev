// GlassesUp — a small overlay drawing the glasses shifted UP onto the forehead.
// Rendered additively over the body during the ~700ms push-glasses idle moment
// (Mascot.tsx) so the glasses visibly "ride up" while the hand reaches them.
//
// Registration: MascotBody draws the resting Take-3 round glasses with the left
// lens centered at cx=80 cy=138 r=19, the right lens at cx=160 cy=138 r=19, the
// thin bridge at x=99 y=136 w=42 h=4, and round pupils at cx=80/160 cy=138 r=8.
// This overlay blanks the resting ROUND frame footprint with skin, then redraws
// the Take-3 round frame translated UP by 24px (cy 138 → 114) so it reads as
// glasses pushed onto the forehead. hex → var(--mascot-*) per the SPRITE SYSTEM
// palette in MascotBody.tsx.
//
// Blanking strategy: paint var(--mascot-skin) over the RESTING round frame
// outline so the doubled-glasses artifact is eliminated. Skin circles slightly
// larger than the frame (r=21) cover each resting lens stroke; a skin rect
// covers the bridge. The pupils (data-mascot-eye, cx=80/160 cy=138 r=8) sit at
// the eye row and are deliberately NOT blanked — when the frame rides up the
// eyes stay put, which is exactly the "glasses pushed up off the eyes" read.
// The skin lens FILLS are part of the resting footprint and get blanked too;
// they are re-drawn at the raised position with the raised frame.
export default function GlassesUp() {
  return (
    <g>
      {/* ── Blank the resting round glasses frame — paint skin over the
            resting lens outlines + bridge so the body's resting glasses
            don't show through behind the raised position. r=21 skin circles
            fully cover the r=19 (3.5px-stroke) resting frame; the pupils
            underneath are left alone (they stay at the eye row). ── */}
      <circle fill="var(--mascot-skin)" cx={80} cy={138} r={21} />
      <circle fill="var(--mascot-skin)" cx={160} cy={138} r={21} />
      {/* bridge blank */}
      <rect fill="var(--mascot-skin)" x={99} y={134} width={42} height={8} />
      {/* Re-draw the resting pupils + glints on top of the skin blanking, so
          the eyes still read while the frame is pushed up off them. ── */}
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={80} cy={138} r={8} />
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={160} cy={138} r={8} />
      <rect data-mascot-eye fill="var(--canvas)" x={83} y={131} width={4} height={4} />
      <rect data-mascot-eye fill="var(--canvas)" x={163} y={131} width={4} height={4} />

      {/* ── Raised glasses — Take-3 round frame translated UP by 24px
            (resting cy=138 → raised cy=114), so it reads as glasses pushed
            onto the forehead. Lens fills + frames + bridge move; pupils do
            NOT (the eyes stay at the resting row, drawn above). ── */}
      {/* clear (skin-toned) lens fills, raised */}
      <circle fill="var(--mascot-skin)" cx={80} cy={114} r={19} />
      <circle fill="var(--mascot-skin)" cx={160} cy={114} r={19} />
      {/* thin dark round frames, raised */}
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={80} cy={114} r={19} />
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={160} cy={114} r={19} />
      {/* thin bridge, raised */}
      <rect fill="var(--mascot-suit)" x={99} y={112} width={42} height={4} />
    </g>
  );
}
