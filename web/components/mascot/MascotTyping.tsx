"use client";

// The side-typing scene — the "thinking" state. Mascot in left profile
// typing on a sleek aluminum laptop (card D, ~110° lid). Pixel-art
// regenerated to match typing-side-v6-lid-angles.html card D in the
// committed reference folder. viewBox 0 0 360 320.
//
// NOTE: this is a SEPARATE scene from the front-view MascotBody — it is a
// left-profile view, so it does not reuse MascotBody. It re-uses the same
// --mascot-* palette so it reads as the same character. Mascot parts snap
// to the 10px grid; the angled laptop lid uses <polygon> (grid-exempt by
// nature — an angled slab cannot land on an axis-aligned grid).
export default function MascotTyping() {
  return (
    <svg
      viewBox="0 0 360 320"
      role="img"
      aria-label="JLBC budget assistant — searching"
      style={{ shapeRendering: "crispEdges" }}
      className="mascot-typing"
    >
      {/* ── Ground shadow — neutral, literal hex (not a mascot-palette part) ── */}
      <rect fill="#cbbfad" x={60} y={290} width={150} height={20} />
      <rect fill="#a89e8e" x={50} y={300} width={170} height={10} />

      {/* ════════════════ MASCOT — left profile ════════════════
          Faces RIGHT (toward the laptop). Cap crown sits up-left, brim
          juts out to the right over the face. Built on the 10px grid. */}

      {/* ── Cap — civic-blue crown, stepped top + back side panel ── */}
      <rect fill="var(--mascot-cap)" x={60} y={30} width={110} height={60} />
      <rect fill="var(--mascot-cap)" x={70} y={20} width={90} height={10} />
      <rect fill="var(--mascot-cap)" x={50} y={50} width={10} height={40} />
      {/* Cap highlight — light band along the two upper edges */}
      <rect fill="var(--mascot-cap-hi)" x={60} y={30} width={110} height={10} />
      <rect fill="var(--mascot-cap-hi)" x={70} y={20} width={90} height={10} />

      {/* ── Brim — juts forward (right) over the face, darker blue ── */}
      <rect fill="var(--mascot-cap)" x={160} y={80} width={40} height={10} />
      <rect fill="var(--mascot-brim)" x={160} y={90} width={50} height={10} />

      {/* ── Head — skin mass, profile. Core block + stepped back panel ── */}
      <rect fill="var(--mascot-skin)" x={60} y={90} width={110} height={80} />
      <rect fill="var(--mascot-skin)" x={50} y={100} width={10} height={60} />
      {/* Nose — small skin nub pushing out to the right */}
      <rect fill="var(--mascot-skin)" x={170} y={120} width={10} height={20} />
      {/* Skin shadow — under the cap brim and along the nose underside */}
      <rect fill="var(--mascot-skin-shadow)" x={60} y={90} width={110} height={10} />
      <rect fill="var(--mascot-skin-shadow)" x={170} y={130} width={10} height={10} />
      {/* Skin highlight — catch-light on the forward cheek */}
      <rect fill="var(--mascot-skin-hi)" x={150} y={140} width={10} height={20} />

      {/* ── Mouth — calm closed line on the forward face ── */}
      <rect fill="var(--mascot-skin-shadow)" x={160} y={150} width={10} height={10} />

      {/* ── Jaw underside — thin skin shadow strip at the chin ── */}
      <rect fill="var(--mascot-skin)" x={60} y={170} width={100} height={10} />
      <rect fill="var(--mascot-skin-shadow)" x={60} y={170} width={100} height={10} />

      {/* ── Glasses — dark frame in profile: temple bar + forward lens ── */}
      {/* temple arm running back over the ear */}
      <rect fill="var(--mascot-suit)" x={80} y={120} width={60} height={10} />
      {/* forward lens — single visible lens in profile */}
      <rect fill="var(--mascot-suit)" x={140} y={110} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={140} y={130} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={140} y={120} width={10} height={10} />
      <rect fill="var(--mascot-suit)" x={170} y={120} width={10} height={10} />
      {/* lens glass — faint paper-white tint inside the frame */}
      <rect fill="var(--canvas)" x={150} y={120} width={20} height={10} opacity={0.5} />
      {/* eye — single eye visible in profile */}
      <rect data-mascot-eye fill="var(--mascot-suit)" x={160} y={120} width={10} height={10} />

      {/* ── Neck — skin block bridging head and torso ── */}
      <rect fill="var(--mascot-skin)" x={100} y={180} width={40} height={20} />

      {/* ── Torso — suit block. Back edge (left) gets the deep shadow strip,
            front edge (right) gets the lighter highlight strip. ── */}
      <rect fill="var(--mascot-suit)" x={70} y={200} width={80} height={90} />
      <rect fill="var(--mascot-suit-shadow)" x={70} y={200} width={10} height={90} />
      <rect fill="var(--mascot-suit-hi)" x={140} y={200} width={10} height={50} />

      {/* ── Shirt collar + tie — forward face of the suit ── */}
      <rect fill="var(--canvas)" x={140} y={200} width={10} height={20} />
      <rect fill="var(--mascot-cap)" x={140} y={210} width={10} height={40} />

      {/* ── Forearm — suit sleeve reaching forward to the keyboard ── */}
      <rect fill="var(--mascot-suit)" x={140} y={220} width={60} height={20} />
      <rect fill="var(--mascot-suit-hi)" x={140} y={220} width={60} height={10} />
      <rect fill="var(--mascot-suit-shadow)" x={190} y={220} width={10} height={20} />

      {/* ════════════════ LAPTOP — sleek aluminum ════════════════
          Silver body is NOT themed — literal hex (its own palette).
          The screen fill is civic-blue (var(--mascot-cap)); screen text
          is paper-white (var(--canvas)). */}

      {/* ── Base — stacked silver slab, keys on top ── */}
      <rect fill="#eef0f2" x={200} y={260} width={84} height={2} />
      <rect fill="#a8acb2" x={200} y={262} width={84} height={6} />
      <rect fill="#c8ccd0" x={200} y={268} width={84} height={4} />
      <rect fill="#6a6e74" x={200} y={272} width={84} height={2} />
      {/* keycaps — dark trim */}
      <g fill="#1a1d22">
        <rect x={204} y={264} width={11} height={2} />
        <rect x={218} y={264} width={11} height={2} />
        <rect x={232} y={264} width={11} height={2} />
        <rect x={246} y={264} width={11} height={2} />
        <rect x={260} y={264} width={11} height={2} />
        <rect x={274} y={264} width={6} height={2} />
      </g>

      {/* ── Hinge — dark silver block where the lid pivots ── */}
      <rect fill="#6a6e74" x={270} y={258} width={14} height={4} />

      {/* ── Lid — card D, ~110° (slight back lean). Angled slab built from
            polygons: bezel face turned toward the mascot, silver back,
            and the civic-blue screen inset. ── */}
      {/* Bezel — dark front face of the lid, angled up-and-back */}
      <polygon fill="#1a1d22" points="232,262 274,262 282,198 240,196" />
      {/* Lid back — silver, the back face of the slab */}
      <polygon fill="#c8ccd0" points="274,262 282,260 290,196 282,198" />
      <polygon fill="#a8acb2" points="282,260 284,260 292,196 290,196" />
      {/* Screen — civic-blue inset inside the bezel */}
      <polygon fill="var(--mascot-cap)" points="236,260 272,260 280,200 244,200" />
      {/* Screen text — paper-white lines of "search results" */}
      <rect fill="var(--canvas)" x={246} y={208} width={28} height={2} />
      <rect fill="var(--canvas)" x={246} y={214} width={32} height={2} />
      <rect fill="var(--canvas)" x={246} y={220} width={26} height={2} />
      <rect fill="var(--canvas)" x={246} y={226} width={30} height={2} />
      <rect fill="var(--canvas)" x={246} y={232} width={20} height={2} />
      {/* Blinking cursor — paper-white, animated via .mascot-typing-cursor */}
      <rect
        className="mascot-typing-cursor"
        fill="var(--canvas)"
        x={246}
        y={240}
        width={3}
        height={4}
      />
      {/* Lid top edge — light silver highlight along the lid's far edge */}
      <rect fill="#eef0f2" x={240} y={192} width={52} height={4} />

      {/* ── Typing hand — own <g> so transform-box: fill-box gives the tap
            animation a hand-local transform-origin. Skin nub on the keys. ── */}
      <g className="mascot-typing-hand">
        <rect fill="var(--mascot-skin)" x={198} y={240} width={22} height={14} />
        <rect fill="var(--mascot-skin-shadow)" x={198} y={250} width={22} height={4} />
        {/* finger separations — thin skin-shadow gaps */}
        <rect fill="var(--mascot-skin-shadow)" x={206} y={240} width={2} height={14} />
        <rect fill="var(--mascot-skin-shadow)" x={213} y={240} width={2} height={14} />
      </g>
    </svg>
  );
}
