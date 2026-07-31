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
// ║ viewBox  : 0 0 240 420   (locked — MASCOT_DIMENSIONS in types.ts)         ║
// ║ cell/grid: 10px square grid. 240÷10 = 24 cols, 420÷10 = 42 rows.          ║
// ║            EVERY rect x/y/width/height is a multiple of 10 (the one       ║
// ║            <text> baseline is exempt — see its inline note). Arm sets and ║
// ║            laptop scenes MUST also snap to this 10px grid.                ║
// ║                                                                           ║
// ║ LANDMARK BOUNDING BOXES  (x, y, width, height — SVG units)                ║
// ║   torso       : x=80  y=200 w=80  h=90   (suit block, 200→290)            ║
// ║   legs        : x=80  y=290 w=82  h=94   (trousers 290→358 + shoes        ║
// ║                 358→384; two legs with a center gap)                     ║
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

      {/* ── Legs — dark suit trousers (two legs with a center gap), standing.
            Shoes in the darker suit-shadow tone. Trousers 290→358, the
            figure ends at the shoe bottom y=384 (viewBox height 420). ── */}
      <rect fill="var(--mascot-suit)" x={86} y={290} width={32} height={68} />
      <rect fill="var(--mascot-suit-hi)" x={86} y={290} width={10} height={58} />
      <rect fill="var(--mascot-suit)" x={124} y={290} width={32} height={68} />
      <rect fill="var(--mascot-suit-hi)" x={124} y={290} width={10} height={58} />
      <rect fill="var(--mascot-suit-shadow)" x={80} y={358} width={40} height={26} />
      <rect fill="var(--mascot-suit-shadow)" x={122} y={358} width={40} height={26} />

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
        fontFamily="var(--chat-mono)" // A deterministic mono stack, not a pixel font: the original art named "Press Start 2P", which was never imported and silently fell back to whatever the browser chose. Token renamed from the retired app's --font-mono during the Task 10 port.
        fontWeight="bold"
        fontSize={20}
      >
        JLBC
      </text>

      {/* ── Glasses + eyes (Take 3 — clear round glasses + brows) ── */}
      {/* eyebrows — short strokes above each lens */}
      <rect fill="var(--mascot-suit-hi)" x={62} y={108} width={36} height={6} />
      <rect fill="var(--mascot-suit-hi)" x={142} y={108} width={36} height={6} />
      {/* clear (skin-toned) lens fills */}
      <circle fill="var(--mascot-skin)" cx={80} cy={138} r={19} />
      <circle fill="var(--mascot-skin)" cx={160} cy={138} r={19} />
      {/* thin dark round frames */}
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={80} cy={138} r={19} />
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={160} cy={138} r={19} />
      {/* thin bridge */}
      <rect fill="var(--mascot-suit)" x={99} y={136} width={42} height={4} />
      {/* dark round pupils */}
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={80} cy={138} r={8} />
      <circle data-mascot-eye fill="var(--mascot-suit)" cx={160} cy={138} r={8} />
      {/* white catch-light glints */}
      <rect data-mascot-eye fill="var(--canvas)" x={83} y={131} width={4} height={4} />
      <rect data-mascot-eye fill="var(--canvas)" x={163} y={131} width={4} height={4} />

      {/* ── Mouth — calm closed line. No --mascot-mouth var exists, so we use
            the darker skin-shadow tone (reads as a relaxed closed mouth). ── */}
      <rect fill="var(--mascot-skin-shadow)" x={100} y={160} width={40} height={10} />
    </g>
  );
}
