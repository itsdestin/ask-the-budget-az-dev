"use client";

// The front-presenting scene — the brief "here's what I found" beat
// after a successful turn. Pixel-art regenerated to match the
// #front-presenting symbol in typing-side-present-v2.html (committed
// reference folder). viewBox 0 0 320 400.
//
// This is the front-VIEW companion to the side-profile MascotTyping
// scene: same character, same --mascot-* palette, so the two read as
// the same mascot. The mascot is built on the 10px grid (same grid as
// MascotBody). Everything — mascot AND laptop — is axis-aligned
// <rect> pixel art: no <polygon>, so the laptop matches the chunky
// pixel style of the rest of the figure.
export default function MascotPresenting() {
  return (
    <svg
      viewBox="0 0 320 400"
      role="img"
      aria-label="JLBC budget assistant — presenting results"
      style={{ shapeRendering: "crispEdges" }}
      className="mascot-presenting"
    >
      {/* ════════════════ MASCOT — front view ════════════════
          Same character/proportions as MascotBody, shifted right so the
          figure sits centered above the laptop. Built on the 10px grid.
          Offset from MascotBody is (dx=+40, dy=-10). */}

      {/* ── Torso — suit block, highlight strips down both edges ── */}
      <rect fill="var(--mascot-suit)" x={120} y={190} width={80} height={90} />
      <rect fill="var(--mascot-suit-hi)" x={120} y={190} width={10} height={60} />
      <rect fill="var(--mascot-suit-hi)" x={190} y={190} width={10} height={60} />

      {/* ── Legs — standing suit trousers (two legs with a center gap),
            matching MascotBody's leg design. MascotBody legs span
            x=86..162 below an x=80 torso; this scene's torso is offset
            +40 to x=120, so the legs shift to x=126..208. Torso bottom
            here is y=280, so trousers run 280→348 (68px), shoes
            348→374 (26px). suit-shadow shoes. ── */}
      <rect fill="var(--mascot-suit)" x={126} y={280} width={32} height={68} />
      <rect fill="var(--mascot-suit-hi)" x={126} y={280} width={10} height={58} />
      <rect fill="var(--mascot-suit)" x={164} y={280} width={32} height={68} />
      <rect fill="var(--mascot-suit-hi)" x={164} y={280} width={10} height={58} />
      <rect fill="var(--mascot-suit-shadow)" x={120} y={348} width={40} height={26} />
      <rect fill="var(--mascot-suit-shadow)" x={162} y={348} width={40} height={26} />

      {/* ── Shirt V — paper-white collar opening, stepped inward ── */}
      <rect fill="var(--canvas)" x={140} y={190} width={40} height={10} />
      <rect fill="var(--canvas)" x={150} y={200} width={20} height={10} />
      {/* (no dead-paint rect at 150,210 — the tie below covers it) */}

      {/* ── Tie — civic-blue, drops down the shirt front ── */}
      <rect fill="var(--mascot-cap)" x={150} y={210} width={10} height={50} />

      {/* ── Neck — skin block bridging head and torso ── */}
      <rect fill="var(--mascot-skin)" x={150} y={170} width={20} height={20} />

      {/* ── Head — core skin block plus stepped side panels ── */}
      <rect fill="var(--mascot-skin)" x={80} y={30} width={160} height={140} />
      <rect fill="var(--mascot-skin)" x={70} y={40} width={10} height={120} />
      <rect fill="var(--mascot-skin)" x={240} y={40} width={10} height={120} />
      <rect fill="var(--mascot-skin)" x={60} y={60} width={10} height={80} />
      <rect fill="var(--mascot-skin)" x={250} y={60} width={10} height={80} />
      {/* Skin highlight — left cheek catch-light */}
      <rect fill="var(--mascot-skin-hi)" x={80} y={100} width={10} height={50} />

      {/* ── Cap — civic-blue crown with stepped top and side panels ── */}
      <rect fill="var(--mascot-cap)" x={80} y={10} width={160} height={60} />
      <rect fill="var(--mascot-cap)" x={70} y={30} width={10} height={40} />
      <rect fill="var(--mascot-cap)" x={240} y={30} width={10} height={40} />
      {/* Cap highlight — light band along the two upper edges */}
      <rect fill="var(--mascot-cap-hi)" x={80} y={10} width={160} height={10} />
      <rect fill="var(--mascot-cap-hi)" x={90} y={0} width={140} height={10} />

      {/* ── Brim — darker blue, two stacked rows widening downward ── */}
      <rect fill="var(--mascot-brim)" x={60} y={70} width={200} height={10} />
      <rect fill="var(--mascot-brim)" x={50} y={80} width={220} height={10} />

      {/* ── Cap shadow cast onto the forehead ── */}
      <rect fill="var(--mascot-skin-shadow)" x={80} y={90} width={160} height={10} />

      {/* ── JLBC — cap text. <text> so the look matches MascotBody. ── */}
      <text
        fill="var(--canvas)"
        x={160}
        y={54} // y is the SVG text baseline — intentionally off the 10px rect grid for optical centering in the cap crown
        textAnchor="middle"
        fontFamily="var(--font-mono)" // app's loaded monospace stack — deterministic, matches MascotBody
        fontWeight="bold"
        fontSize={20}
      >
        JLBC
      </text>

      {/* ── Glasses + eyes (Take 3 — clear round glasses + brows) ──
            Same Take-3 art as MascotBody, re-anchored to this component's
            head. MascotBody's eye row sits at cx=80/160 cy=138; this head is
            offset by (dx=+40, dy=-10), so every coordinate is shifted to
            match: lens centers cx=120/200 cy=128. ── */}
      {/* eyebrows — short strokes above each lens */}
      <rect fill="var(--mascot-suit-hi)" x={102} y={98} width={36} height={6} />
      <rect fill="var(--mascot-suit-hi)" x={182} y={98} width={36} height={6} />
      {/* clear (skin-toned) lens fills */}
      <circle fill="var(--mascot-skin)" cx={120} cy={128} r={19} />
      <circle fill="var(--mascot-skin)" cx={200} cy={128} r={19} />
      {/* thin dark round frames */}
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={120} cy={128} r={19} />
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={200} cy={128} r={19} />
      {/* thin bridge */}
      <rect fill="var(--mascot-suit)" x={139} y={126} width={42} height={4} />
      {/* dark round pupils */}
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={120} cy={128} r={8} />
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={200} cy={128} r={8} />
      {/* white catch-light glints */}
      <rect data-mascot-eye fill="var(--canvas)" x={123} y={121} width={4} height={4} />
      <rect data-mascot-eye fill="var(--canvas)" x={203} y={121} width={4} height={4} />

      {/* ── Mouth — calm closed line ── */}
      <rect fill="var(--mascot-skin-shadow)" x={140} y={150} width={40} height={10} />

      {/* ── Arms — suit upper-arm stubs hanging outside the torso, then
            forearms angling inward and down to the laptop. Skin hands
            rest open at the keyboard's near edge. ── */}
      {/* left upper arm */}
      <rect fill="var(--mascot-suit)" x={100} y={200} width={20} height={30} />
      <rect fill="var(--mascot-suit-hi)" x={100} y={200} width={10} height={30} />
      {/* left forearm reaching in toward the keyboard */}
      <rect fill="var(--mascot-suit)" x={100} y={230} width={40} height={20} />
      {/* left hand — open skin nub on the near keyboard edge */}
      <rect fill="var(--mascot-skin)" x={90} y={232} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={90} y={246} width={20} height={6} />

      {/* right upper arm */}
      <rect fill="var(--mascot-suit)" x={200} y={200} width={20} height={30} />
      <rect fill="var(--mascot-suit-hi)" x={210} y={200} width={10} height={30} />
      {/* right forearm reaching in toward the keyboard */}
      <rect fill="var(--mascot-suit)" x={180} y={230} width={40} height={20} />
      {/* right hand — open skin nub on the near keyboard edge */}
      <rect fill="var(--mascot-skin)" x={210} y={232} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={210} y={246} width={20} height={6} />

      {/* ════════════════ LAPTOP — front-presented, pixel-art ════════════
          Rebuilt as chunky axis-aligned <rect>s (no <polygon>) so it
          matches the rest of the mascot's pixel-art style. Drawn
          straight-on: an upright screen panel above a base/keyboard
          slab. The silver body is NOT themed — small flat literal-hex
          palette (#c8ccd0 light silver, #6a6e74 darker shade). Screen
          fill is civic-blue (var(--mascot-cap)); screen text + the
          citation chip label are paper-white (var(--canvas)); the
          citation chip pill is civic-blue. Held in the hands at the
          keyboard line (hands rest at y≈232..252).

          SCALED DOWN ~13% from the original draw (screen frame
          120×90 → 104×78, base 140w → 120w) per user note that the
          laptop "looks good, but may need to be scaled down slightly."
          Re-centered on x=160 — the laptop's horizontal center is
          unchanged, it is just smaller. */}

      {/* ── Screen panel — upright silver-framed rect, civic-blue inset.
            Frame 104×78 (was 120×90), centered on x=160 → x=108..212. ── */}
      {/* dark-silver outer frame */}
      <rect fill="#6a6e74" x={108} y={176} width={104} height={78} />
      {/* light-silver bezel surround inside the frame */}
      <rect fill="#c8ccd0" x={112} y={180} width={96} height={70} />
      {/* screen — civic-blue inset */}
      <rect fill="var(--mascot-cap)" x={118} y={186} width={84} height={56} />

      {/* ── Screen contents — paper-white answer text, a civic-blue
            citation chip, and a blinking cursor. Re-fit inside the
            smaller blue panel (x 118..202, y 186..242). ── */}
      <rect fill="var(--canvas)" x={124} y={194} width={52} height={4} />
      <rect fill="var(--canvas)" x={124} y={202} width={70} height={4} />
      <rect fill="var(--canvas)" x={124} y={210} width={60} height={4} />
      <rect fill="var(--canvas)" x={124} y={218} width={44} height={4} />
      {/* citation chip — a small civic-blue pill, with a paper-white
          label bar inside it standing in for the cite text */}
      <rect fill="var(--mascot-cap)" x={124} y={228} width={40} height={10} />
      <rect fill="var(--canvas)" x={128} y={231} width={32} height={4} />
      {/* Blinking cursor — paper-white, reuses the existing
          .mascot-typing-cursor keyframe (already in globals.css) */}
      <rect
        className="mascot-typing-cursor"
        fill="var(--canvas)"
        x={182}
        y={228}
        width={4}
        height={8}
      />

      {/* ── Base / keyboard slab — chunky silver rect below the screen.
            Wider than the screen so the laptop reads as an open
            clamshell seen straight-on. 120w (was 140w), centered on
            x=160 → x=100..220. ── */}
      {/* light-silver deck */}
      <rect fill="#c8ccd0" x={100} y={254} width={120} height={14} />
      {/* dark-silver front lip */}
      <rect fill="#6a6e74" x={100} y={268} width={120} height={6} />
      {/* keycap rows — dark trim on the deck, on the 10px-ish grid */}
      <g fill="#6a6e74">
        <rect x={108} y={258} width={14} height={4} />
        <rect x={126} y={258} width={14} height={4} />
        <rect x={144} y={258} width={14} height={4} />
        <rect x={162} y={258} width={14} height={4} />
        <rect x={180} y={258} width={14} height={4} />
        <rect x={198} y={258} width={14} height={4} />
      </g>
    </svg>
  );
}
