"use client";

// The front-presenting scene — the brief "here's what I found" beat
// after a successful turn. Pixel-art regenerated to match the
// #front-presenting symbol in typing-side-present-v2.html (committed
// reference folder). viewBox 0 0 320 320.
//
// This is the front-VIEW companion to the side-profile MascotTyping
// scene: same character, same --mascot-* palette, so the two read as
// the same mascot. The mascot is built on the 10px grid (same grid as
// MascotBody). The laptop is tilted forward to show its screen to the
// viewer, so its slabs are <polygon> (grid-exempt by nature — an
// angled slab cannot land on an axis-aligned grid).
export default function MascotPresenting() {
  return (
    <svg
      viewBox="0 0 320 320"
      role="img"
      aria-label="JLBC budget assistant — presenting results"
      style={{ shapeRendering: "crispEdges" }}
      className="mascot-presenting"
    >
      {/* ── Ground shadow — neutral, literal hex (not a mascot-palette
            part). Same colors MascotBody/MascotTyping use. ── */}
      <rect fill="#cbbfad" x={70} y={290} width={180} height={20} />
      <rect fill="#a89e8e" x={60} y={300} width={200} height={10} />

      {/* ════════════════ MASCOT — front view ════════════════
          Same character/proportions as MascotBody, shifted right so the
          figure sits centered above the tilted laptop. Built on the
          10px grid. */}

      {/* ── Torso — suit block, highlight strips down both edges ── */}
      <rect fill="var(--mascot-suit)" x={120} y={190} width={80} height={90} />
      <rect fill="var(--mascot-suit-hi)" x={120} y={190} width={10} height={60} />
      <rect fill="var(--mascot-suit-hi)" x={190} y={190} width={10} height={60} />

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

      {/* ── Glasses — dark frame: left lens, right lens, and bridge ── */}
      {/* left lens */}
      <rect fill="var(--mascot-suit)" x={100} y={110} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={100} y={140} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={100} y={120} width={10} height={20} />
      <rect fill="var(--mascot-suit)" x={130} y={120} width={10} height={20} />
      {/* right lens */}
      <rect fill="var(--mascot-suit)" x={180} y={110} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={180} y={140} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={180} y={120} width={10} height={20} />
      <rect fill="var(--mascot-suit)" x={210} y={120} width={10} height={20} />
      {/* bridge */}
      <rect fill="var(--mascot-suit)" x={140} y={120} width={40} height={10} />

      {/* ── Eyes — two separate rects ── */}
      <rect fill="var(--mascot-suit)" x={110} y={120} width={20} height={10} />
      <rect fill="var(--mascot-suit)" x={190} y={120} width={20} height={10} />

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

      {/* ════════════════ LAPTOP — tilted forward ════════════════
          Silver body is NOT themed — literal hex, the same five colors
          as MascotTyping. The screen fill is civic-blue
          (var(--mascot-cap)); screen text + the citation chip text are
          paper-white (var(--canvas)); the citation chip is civic-blue.
          All laptop slabs are <polygon> — the laptop is tilted toward
          the viewer, so it is grid-exempt by nature. */}

      {/* ── Keyboard deck — top face tilted toward the viewer ── */}
      <polygon fill="#c8ccd0" points="60,286 260,286 248,260 72,260" />
      <polygon fill="#6a6e74" points="60,286 260,286 256,290 64,290" />
      {/* recessed key bed */}
      <polygon fill="#a8acb2" points="76,282 244,282 236,264 84,264" />
      {/* keycaps — dark trim; grid-exempt: sized to the tilted deck */}
      <g fill="#1a1d22">
        <rect x={84} y={268} width={14} height={3} />
        <rect x={104} y={268} width={14} height={3} />
        <rect x={124} y={268} width={14} height={3} />
        <rect x={144} y={268} width={14} height={3} />
        <rect x={164} y={268} width={14} height={3} />
        <rect x={184} y={268} width={14} height={3} />
        <rect x={204} y={268} width={14} height={3} />
        <rect x={224} y={268} width={14} height={3} />
        <rect x={88} y={274} width={14} height={3} />
        <rect x={108} y={274} width={14} height={3} />
        <rect x={128} y={274} width={14} height={3} />
        <rect x={148} y={274} width={14} height={3} />
        <rect x={168} y={274} width={14} height={3} />
        <rect x={188} y={274} width={14} height={3} />
        <rect x={208} y={274} width={14} height={3} />
        <rect x={226} y={274} width={14} height={3} />
      </g>

      {/* ── Lid — tilted up-and-back. Dark bezel frame, silver back
            highlight, civic-blue screen inset. ── */}
      {/* bezel — dark frame face */}
      <polygon fill="#1a1d22" points="72,260 248,260 240,170 80,170" />
      {/* lid back highlight — light silver along the lid's outer face */}
      <polygon fill="#c8ccd0" points="76,256 244,256 236,174 84,174" />
      {/* screen — civic-blue inset inside the bezel */}
      <polygon fill="var(--mascot-cap)" points="84,250 236,250 228,180 92,180" />

      {/* ── Screen contents — paper-white answer text, a civic-blue
            citation chip, and a blinking cursor. ── */}
      <rect fill="var(--canvas)" x={94} y={186} width={80} height={3} />
      <rect fill="var(--canvas)" x={94} y={196} width={120} height={3} />
      <rect fill="var(--canvas)" x={94} y={206} width={100} height={3} />
      <rect fill="var(--canvas)" x={94} y={216} width={90} height={3} />
      <rect fill="var(--canvas)" x={94} y={226} width={60} height={3} />
      {/* citation chip — a small civic-blue pill, with a paper-white
          label bar inside it standing in for the cite text */}
      <rect fill="var(--mascot-cap)" x={94} y={236} width={40} height={8} />
      <rect fill="var(--canvas)" x={98} y={239} width={32} height={2} />
      {/* Blinking cursor — paper-white, reuses the existing
          .mascot-typing-cursor keyframe (already in globals.css) */}
      <rect
        className="mascot-typing-cursor"
        fill="var(--canvas)"
        x={160}
        y={236}
        width={3}
        height={6}
      />
    </svg>
  );
}
