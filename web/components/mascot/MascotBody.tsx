// The shared mascot body: head, cap, glasses, face, torso.
// Arms are composed on top by Mascot.tsx. Pixel-art regenerated to match
// the #body symbol in the committed reference mockup
// (specs/assets/2026-05-15-mascot-reference/mascot-pixel-poses.html);
// every mascot fill is a --mascot-* CSS variable.
//
// ╔═══════════════════════════════════════════════════════════════════════════╗
// ║ SPRITE SYSTEM — canonical sprite spec. Tasks 5–8 (arm sets + laptop        ║
// ║ scenes) MUST register against these coordinates. Quantitative, not prose. ║
// ╠═══════════════════════════════════════════════════════════════════════════╣
// ║ viewBox  : 0 0 240 320   (locked — MASCOT_DIMENSIONS in types.ts)         ║
// ║ cell/grid: 10px square grid. 240÷10 = 24 cols, 320÷10 = 32 rows.          ║
// ║            EVERY rect x/y/width/height is a multiple of 10 (the one       ║
// ║            <text> baseline is exempt — see its inline note). Arm sets and ║
// ║            laptop scenes MUST also snap to this 10px grid.                ║
// ║                                                                           ║
// ║ LANDMARK BOUNDING BOXES  (x, y, width, height — SVG units)                ║
// ║   torso       : x=80  y=200 w=80  h=90   (suit block, 200→290)            ║
// ║   neck        : x=110 y=180 w=20  h=20   (skin, behind torso top)         ║
// ║   head        : x=20  y=40  w=200 h=140  (skin mass incl. side panels;    ║
// ║                 core block 40,40,160,140 + ear panels out to x=20/220)    ║
// ║   cap         : x=30  y=10  w=180 h=80   (crown 40,10 → brim underside;   ║
// ║                 crown block 40,20,160,60 + top 50,10,140,10 +             ║
// ║                 left side panel 30,40,10,40 + right side panel 200,40,10,40)║
// ║   brim        : x=10  y=80  w=220 h=20   (two rects: 20,80,200,10 +       ║
// ║                 10,90,220,10)                                             ║
// ║                                                                           ║
// ║ ARM ATTACHMENT POINTS  (where Task 5 arm sets connect)                    ║
// ║   shoulder line y : 210   (top edge of every arm set)                     ║
// ║   LEFT  shoulder  : x = 60 .. 80   (arm hangs OUTSIDE torso, torso L=80)  ║
// ║   RIGHT shoulder  : x = 160 .. 180 (arm hangs OUTSIDE torso, torso R=160) ║
// ║   arm-set rect    : default hanging arm = 20w stub from y=210; torso edge ║
// ║                     is the inner attachment seam. Arms render ON TOP of   ║
// ║                     the body <g>, so a 10px overlap into the torso        ║
// ║                     (x 70..80 left, 160..170 right) is the clean seam.    ║
// ║                                                                           ║
// ║ PALETTE  (reference hex → CSS variable)                                   ║
// ║   #3a6ea5 cap            → var(--mascot-cap)                               ║
// ║   #5a8cc4 cap highlight  → var(--mascot-cap-hi)                            ║
// ║   #2c557f brim           → var(--mascot-brim)                             ║
// ║   #e8c8a4 skin           → var(--mascot-skin)                             ║
// ║   #c8a47e skin shadow    → var(--mascot-skin-shadow)                       ║
// ║   #f4dab7 skin highlight → var(--mascot-skin-hi)                           ║
// ║   #1f2937 suit/frame/eye → var(--mascot-suit)                              ║
// ║   #303a4a suit highlight → var(--mascot-suit-hi)                           ║
// ║   #13181f suit shadow    → var(--mascot-suit-shadow)                       ║
// ║   #fbf7f0 JLBC text/shirt→ var(--canvas)  (paper-white)                    ║
// ║   mouth (#8a5f3f in ref) → var(--mascot-skin-shadow) (no --mascot-mouth    ║
// ║                            var exists; darker-skin line reads as a calm   ║
// ║                            closed mouth)                                  ║
// ╚═══════════════════════════════════════════════════════════════════════════╝
export default function MascotBody() {
  return (
    <g>
      {/* ── Torso — narrower than the head so arm sets hang outside it.
            Suit highlight strips run down the left and right edges. ── */}
      <rect fill="var(--mascot-suit)" x={80} y={200} width={80} height={90} />
      <rect fill="var(--mascot-suit-hi)" x={80} y={200} width={10} height={60} />
      <rect fill="var(--mascot-suit-hi)" x={150} y={200} width={10} height={60} />

      {/* ── Shirt V — paper-white collar opening, stepped inward ── */}
      <rect fill="var(--canvas)" x={100} y={200} width={40} height={10} />
      <rect fill="var(--canvas)" x={110} y={210} width={20} height={10} />
      {/* Dead-paint rect removed: x=110 y=220 w=10 h=10 var(--canvas) was fully
          overpainted by the tie rect immediately below at identical x/y/w. */}

      {/* ── Tie — civic-blue, drops down the shirt front ── */}
      <rect fill="var(--mascot-cap)" x={110} y={220} width={10} height={50} />

      {/* ── Neck — skin block bridging head and torso ── */}
      <rect fill="var(--mascot-skin)" x={110} y={180} width={20} height={20} />

      {/* ── Head — core skin block plus stepped side panels (ears/jaw) ── */}
      <rect fill="var(--mascot-skin)" x={40} y={40} width={160} height={140} />
      <rect fill="var(--mascot-skin)" x={30} y={50} width={10} height={120} />
      <rect fill="var(--mascot-skin)" x={200} y={50} width={10} height={120} />
      <rect fill="var(--mascot-skin)" x={20} y={70} width={10} height={80} />
      <rect fill="var(--mascot-skin)" x={210} y={70} width={10} height={80} />
      {/* Skin highlight — left cheek catch-light */}
      <rect fill="var(--mascot-skin-hi)" x={40} y={110} width={10} height={50} />

      {/* ── Cap — civic-blue crown with stepped top and side panels ── */}
      <rect fill="var(--mascot-cap)" x={40} y={20} width={160} height={60} />
      {/* Dead-paint rect removed: x=50 y=10 w=140 h=10 var(--mascot-cap) was fully
          overpainted by the cap-highlight rect immediately below at identical x/y/w. */}
      <rect fill="var(--mascot-cap)" x={30} y={40} width={10} height={40} />
      <rect fill="var(--mascot-cap)" x={200} y={40} width={10} height={40} />
      {/* Cap highlight — light band along the two upper edges */}
      <rect fill="var(--mascot-cap-hi)" x={40} y={20} width={160} height={10} />
      <rect fill="var(--mascot-cap-hi)" x={50} y={10} width={140} height={10} />

      {/* ── Brim — darker blue, two stacked rows widening downward ── */}
      <rect fill="var(--mascot-brim)" x={20} y={80} width={200} height={10} />
      <rect fill="var(--mascot-brim)" x={10} y={90} width={220} height={10} />

      {/* ── Cap shadow cast onto the forehead ── */}
      <rect fill="var(--mascot-skin-shadow)" x={40} y={100} width={160} height={10} />

      {/* ── JLBC — cap text. <text> element so the smoke test can assert the
            literal "JLBC" substring in rendered HTML. ── */}
      <text
        fill="var(--canvas)"
        x={120}
        y={64} // y is the SVG text baseline — intentionally off the 10px rect grid for optical centering in the cap crown
        textAnchor="middle"
        fontFamily="var(--font-mono)" // Use app's loaded monospace stack (Inter/Source Serif 4 are the loaded fonts; "Press Start 2P" was never imported, so it silently fell back to browser default — deterministic stack preferred)
        fontWeight="bold"
        fontSize={20}
      >
        JLBC
      </text>

      {/* ── Eyebrows — short dark bars above each lens frame, with a 10px
            skin gap between brow and frame. New: gives the face expression. ── */}
      <rect fill="var(--mascot-suit-hi)" x={60} y={100} width={40} height={10} />
      <rect fill="var(--mascot-suit-hi)" x={140} y={100} width={40} height={10} />

      {/* ── Glasses — "Take 3" clear glasses: each lens is a THIN HOLLOW
            frame (one 10px cell thick) outlining a region of bare SKIN, so
            the head shows through the lens. Built as 4 thin rects per lens
            (top/bottom/left/right) plus a 10px bridge bar. ── */}
      {/* left lens frame — hollow outline, skin shows through interior */}
      <rect fill="var(--mascot-suit)" x={60} y={120} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={60} y={150} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={60} y={130} width={10} height={20} />
      <rect fill="var(--mascot-suit)" x={90} y={130} width={10} height={20} />
      {/* right lens frame — hollow outline */}
      <rect fill="var(--mascot-suit)" x={140} y={120} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={140} y={150} width={40} height={10} />
      <rect fill="var(--mascot-suit)" x={140} y={130} width={10} height={20} />
      <rect fill="var(--mascot-suit)" x={170} y={130} width={10} height={20} />
      {/* bridge — 10px-thick bar joining the two lens frames at mid-height */}
      <rect fill="var(--mascot-suit)" x={100} y={130} width={40} height={10} />

      {/* ── Pupils — a solid dark 2×2-cell rect inside each lens, so the eye
            reads clearly against the skin-toned lens interior. data-mascot-eye
            lets the blink animation target each one independently. ── */}
      <rect data-mascot-eye fill="var(--mascot-suit)" x={70} y={130} width={20} height={20} />
      <rect data-mascot-eye fill="var(--mascot-suit)" x={150} y={130} width={20} height={20} />
      {/* ── Glint — small paper-white catch-light on the upper-outer corner of
            each pupil so the eye doesn't read flat. Sub-grid (fine eye detail). ── */}
      <rect fill="var(--canvas)" x={71} y={131} width={5} height={5} />
      <rect fill="var(--canvas)" x={151} y={131} width={5} height={5} />

      {/* ── Mouth — calm closed line. No --mascot-mouth var exists, so we use
            the darker skin-shadow tone (reads as a relaxed closed mouth). ── */}
      <rect fill="var(--mascot-skin-shadow)" x={100} y={160} width={40} height={10} />
    </g>
  );
}
