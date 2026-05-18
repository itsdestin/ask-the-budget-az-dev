"use client";

// The side-typing scene — the "thinking" state. Mascot in left profile,
// SEATED, typing on a laptop resting on his lap. Pixel-art: every part
// is an axis-aligned <rect> on the 10px grid (no <polygon>), so the
// laptop matches the chunky pixel style of the rest of the figure.
// viewBox 0 0 360 380.
//
// NOTE: this is a SEPARATE scene from the front-view MascotBody — it is a
// left-profile view, so it does not reuse MascotBody. It re-uses the same
// --mascot-* palette so it reads as the same character.
//
// SEATED CONSTRUCTION (side profile, faces RIGHT):
//   - head + torso stay upright (same blocks as the old standing pose)
//   - the legs are BENT: a horizontal thigh runs forward from the hip,
//     a knee, then a vertical shin drops to a foot
//   - he sits on a plain chunky block/stool (literal-hex grey)
//   - the laptop rests on the horizontal thighs (his lap) — an L-shaped
//     open clamshell: a horizontal base slab + an upright screen panel
export default function MascotTyping() {
  return (
    <svg
      viewBox="0 0 360 380"
      role="img"
      aria-label="JLBC budget assistant — searching"
      style={{ shapeRendering: "crispEdges" }}
      className="mascot-typing"
    >
      {/* ════════════════ SEAT — plain chunky block/stool ════════════════
          A neutral literal-hex grey block he sits on (a prop, not the
          themed mascot). Sits under the hips; the torso bottom is y=290
          so the seat top is y=290. */}
      <rect fill="#6a6e74" x={60} y={290} width={110} height={20} />
      {/* darker shadow strip down the front face of the stool */}
      <rect fill="#4a4e54" x={60} y={310} width={110} height={50} />
      {/* light-silver catch-light along the seat's top edge */}
      <rect fill="#a8acb2" x={60} y={290} width={110} height={4} />

      {/* ════════════════ MASCOT — left profile, seated ════════════════
          Faces RIGHT (toward the laptop). Cap crown sits up-left, brim
          juts out to the right over the face. Built on the 10px grid. */}

      {/* ── Cap — civic-blue crown, stepped top + back side panel ── */}
      <rect fill="var(--mascot-cap)" x={60} y={30} width={110} height={60} />
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
      {/* Skin shadow — under the cap brim */}
      <rect fill="var(--mascot-skin-shadow)" x={60} y={90} width={110} height={10} />
      {/* Skin highlight — catch-light on the forward cheek */}
      <rect fill="var(--mascot-skin-hi)" x={150} y={140} width={10} height={20} />

      {/* ── Mouth — calm closed line on the forward face ── */}
      <rect fill="var(--mascot-skin-shadow)" x={160} y={150} width={10} height={10} />

      {/* ── Jaw shadow — darker skin-shadow strip at the chin ── */}
      <rect fill="var(--mascot-skin-shadow)" x={60} y={170} width={100} height={10} />

      {/* ── Glasses + eye (Take 3 — clear round glasses) in profile: ONE
            visible lens. Same Take-3 proportions as the front views
            (frame r=19 strokeWidth=3.5, pupil r=8) so the character reads
            consistent. The single round lens is centered at (160, 130). ── */}
      {/* eyebrow — single short stroke above the lens */}
      <rect fill="var(--mascot-suit-hi)" x={142} y={100} width={36} height={6} />
      {/* temple arm running back over the ear to the cap */}
      <rect fill="var(--mascot-suit)" x={80} y={128} width={62} height={4} />
      {/* clear (skin-toned) lens fill */}
      <circle fill="var(--mascot-skin)" cx={160} cy={130} r={19} />
      {/* thin dark round frame */}
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={160} cy={130} r={19} />
      {/* dark round pupil */}
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={160} cy={130} r={8} />
      {/* white catch-light glint */}
      <rect data-mascot-eye fill="var(--canvas)" x={163} y={123} width={4} height={4} />

      {/* ── Neck — skin block bridging head and torso ── */}
      <rect fill="var(--mascot-skin)" x={100} y={180} width={40} height={20} />

      {/* ── Torso — suit block, upright. Back edge (left) gets the deep
            shadow strip, front edge (right) gets the lighter highlight
            strip. Torso bottom is y=290 (the hip line). ── */}
      <rect fill="var(--mascot-suit)" x={70} y={200} width={80} height={90} />
      <rect fill="var(--mascot-suit-shadow)" x={70} y={200} width={10} height={90} />
      <rect fill="var(--mascot-suit-hi)" x={140} y={200} width={10} height={50} />

      {/* ── Shirt collar + tie — forward face of the suit ── */}
      <rect fill="var(--canvas)" x={140} y={200} width={10} height={20} />
      <rect fill="var(--mascot-cap)" x={140} y={210} width={10} height={40} />

      {/* ════════════════ SEATED LEGS — bent for sitting ════════════════
            Thigh runs HORIZONTAL forward (right) from the hip; a knee;
            then the shin runs DOWN to a foot. Trousers var(--mascot-suit),
            shoe var(--mascot-suit-shadow). All axis-aligned rects. The
            thigh top y=290 is the lap surface the laptop rests on. */}

      {/* ── Thigh — horizontal trouser block forward from the hip ── */}
      <rect fill="var(--mascot-suit)" x={70} y={290} width={150} height={30} />
      {/* thigh highlight — light strip along the top of the thigh */}
      <rect fill="var(--mascot-suit-hi)" x={70} y={290} width={150} height={8} />

      {/* ── Shin — vertical trouser block dropping from the knee ── */}
      <rect fill="var(--mascot-suit)" x={190} y={320} width={30} height={50} />
      {/* shin shadow — deep strip down the back edge of the shin */}
      <rect fill="var(--mascot-suit-shadow)" x={190} y={320} width={8} height={50} />

      {/* ── Foot / shoe — suit-shadow nub jutting forward at the shin base ── */}
      <rect fill="var(--mascot-suit-shadow)" x={190} y={364} width={50} height={16} />

      {/* ── Forearm — suit sleeve reaching forward to the keyboard ── */}
      <rect fill="var(--mascot-suit)" x={140} y={236} width={70} height={20} />
      <rect fill="var(--mascot-suit-hi)" x={140} y={236} width={70} height={10} />
      <rect fill="var(--mascot-suit-shadow)" x={200} y={236} width={10} height={20} />

      {/* ════════════════ LAPTOP — open clamshell, pixel-art ════════════
          Rebuilt as chunky axis-aligned <rect>s (no <polygon>) so it
          matches the rest of the mascot's pixel-art style. In side
          profile a laptop is an L-shape: a horizontal base slab + an
          upright screen panel behind it. It rests on the lap — the base
          slab sits on top of the horizontal thighs (thigh top y=290).
          The silver body is NOT themed — small flat literal-hex palette
          (#c8ccd0 light silver, #6a6e74 darker shade). Screen fill is
          civic-blue (var(--mascot-cap)); screen text is paper-white
          (var(--canvas)). */}

      {/* ── Base slab — horizontal, resting on the thighs ── */}
      {/* light-silver deck */}
      <rect fill="#c8ccd0" x={170} y={272} width={110} height={12} />
      {/* dark-silver front lip */}
      <rect fill="#6a6e74" x={170} y={284} width={110} height={6} />
      {/* keycap rows — dark trim on the deck */}
      <g fill="#6a6e74">
        <rect x={180} y={276} width={14} height={4} />
        <rect x={198} y={276} width={14} height={4} />
        <rect x={216} y={276} width={14} height={4} />
        <rect x={234} y={276} width={14} height={4} />
        <rect x={252} y={276} width={14} height={4} />
      </g>

      {/* ── Screen panel — upright rect behind the base, civic-blue inset.
            Stands up at the back of the base slab (its far/right edge). ── */}
      {/* dark-silver outer frame */}
      <rect fill="#6a6e74" x={266} y={182} width={20} height={92} />
      {/* light-silver bezel surround */}
      <rect fill="#c8ccd0" x={244} y={182} width={26} height={92} />
      {/* screen — civic-blue inset facing the mascot (to the left) */}
      <rect fill="var(--mascot-cap)" x={240} y={188} width={26} height={80} />

      {/* ── Screen text — paper-white lines of "search results" ── */}
      <rect fill="var(--canvas)" x={244} y={198} width={18} height={3} />
      <rect fill="var(--canvas)" x={244} y={206} width={20} height={3} />
      <rect fill="var(--canvas)" x={244} y={214} width={16} height={3} />
      <rect fill="var(--canvas)" x={244} y={222} width={19} height={3} />
      <rect fill="var(--canvas)" x={244} y={230} width={14} height={3} />
      {/* Blinking cursor — paper-white, animated via .mascot-typing-cursor */}
      <rect
        className="mascot-typing-cursor"
        fill="var(--canvas)"
        x={244}
        y={240}
        width={4}
        height={6}
      />

      {/* ── Typing hand — own <g> so transform-box: fill-box gives the tap
            animation a hand-local transform-origin. Skin nub on the keys. ── */}
      <g className="mascot-typing-hand">
        <rect fill="var(--mascot-skin)" x={196} y={256} width={24} height={16} />
        <rect fill="var(--mascot-skin-shadow)" x={196} y={268} width={24} height={4} />
        {/* finger separations — thin skin-shadow gaps */}
        <rect fill="var(--mascot-skin-shadow)" x={204} y={256} width={2} height={16} />
        <rect fill="var(--mascot-skin-shadow)" x={211} y={256} width={2} height={16} />
      </g>
    </svg>
  );
}
