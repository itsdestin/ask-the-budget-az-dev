// GlassesUp — a small overlay drawing ONLY the glasses FRAME shifted UP onto
// the forehead. Rendered additively over the body during the ~700ms
// push-glasses idle moment (Mascot.tsx) so the glasses visibly "ride up"
// while the hand reaches them.
//
// Registration: MascotBody draws the resting Take-3 round glasses with the
// left lens centered at cx=80 cy=138 r=19, the right lens at cx=160 cy=138
// r=19, frame strokeWidth=3.5, the thin bridge at x=99 y=136 w=42 h=4, and
// round pupils at cx=80/160 cy=138 r=8 with white glints at x=83/163 y=131
// w=4 h=4. The eyebrows are var(--mascot-suit-hi) bars at x=62/142 y=108
// w=36 h=6 — i.e. they occupy the band y=108..114, ABOVE the lenses.
//
// WHY this overlay no longer draws skin lens-fills: the lenses are "clear"
// (skin-tone) — there is no real lens to move. The previous version drew
// shifted skin <circle>s up at the forehead, and those skin discs painted
// over the eyebrows and erased them. The eyes (pupils + glints) and the
// eyebrows belong to the FACE; they must stay fixed and visible throughout
// the push-glasses moment. Only the glasses FRAME (round stroke outline +
// bridge) moves up. So GlassesUp now: (1) blanks ONLY the resting frame
// band with skin — never reaching the brow band — (2) re-draws the resting
// eyes on top of that blank, (3) leaves the eyebrows completely untouched
// (MascotBody's brows show through), and (4) draws the raised frame high
// enough on the forehead to clear the brows.
//
// hex → var(--mascot-*) per the SPRITE SYSTEM palette in MascotBody.tsx.
export default function GlassesUp() {
  // Resting lens centers / radius — must match MascotBody exactly.
  const restCy = 138;
  const lensR = 19;
  // Raised frame center. Eyebrows occupy y=108..114; the raised frame's
  // outer edge is cy - (lensR + strokeWidth/2) ≈ cy - 20.75. To keep that
  // lower edge ABOVE the brow top (y=108) we need cy ≤ ~87. Shift up 52px
  // (restCy 138 → 86): lower frame edge ≈ 106.75, clear of the brows.
  const raisedCy = 86;

  return (
    <g>
      {/* ── Blank ONLY the resting round frame band ──
            Skin discs at the RESTING lens centers (cy=138), radius 22 —
            that is the frame outer radius (~20.75) + a hair, enough to
            fully cover the resting r=19 / 3.5px-stroke frame ring. The top
            edge of each disc is 138-22 = 116, which stays BELOW the brow
            bars (y=108..114) — so this blank never touches the eyebrows.
            The resting bridge (y=136..140) is inside this band and gets
            covered by these discs / the bridge blank below. ── */}
      <circle fill="var(--mascot-skin)" cx={80} cy={restCy} r={22} />
      <circle fill="var(--mascot-skin)" cx={160} cy={restCy} r={22} />
      {/* bridge blank — sits at the eye row, top y=132, well below brows */}
      <rect fill="var(--mascot-skin)" x={99} y={132} width={42} height={12} />

      {/* ── Re-draw the resting eyes on top of the skin blank ──
            The blank discs above cover the body's pupils + glints, so they
            are redrawn here at their original resting position. They keep
            data-mascot-eye so the eye-tracking selector still finds them.
            The eyes stay PUT — only the frame rides up. ── */}
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={80} cy={restCy} r={8} />
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={160} cy={restCy} r={8} />
      <rect data-mascot-eye fill="var(--canvas)" x={83} y={131} width={4} height={4} />
      <rect data-mascot-eye fill="var(--canvas)" x={163} y={131} width={4} height={4} />

      {/* ── Eyebrows: deliberately NOT drawn and NOT blanked here. They are
            painted by MascotBody and show through this overlay untouched. ── */}

      {/* ── Raised glasses FRAME — round stroke outline + bridge only, no
            lens fill. Shifted UP 52px (cy 138 → 86) so the frame sits on
            the forehead clearly above the eyebrows (lower edge ≈ 106.75 vs
            brow top 108). Same strokeWidth + radius as the resting frame. ── */}
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={80} cy={raisedCy} r={lensR} />
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={160} cy={raisedCy} r={lensR} />
      {/* thin bridge, raised with the frame (resting y=136 → 84) */}
      <rect fill="var(--mascot-suit)" x={99} y={84} width={42} height={4} />
    </g>
  );
}
