// ArmsClipboard — P3e. Holding a clipboard (result-settled / "citing source"
// pose). Arm set regenerated to match the #arms-clipboard symbol in the
// committed reference mockup. Conforms to the 10px sprite grid; the left arm
// hangs from the shoulder line y=210, the right arm bends forward across the
// body to support a clipboard held in front of the torso.
//
// Clipboard board is a neutral #a89e8e literal hex (not part of the mascot
// palette); the clipboard paper is paper-white var(--canvas).
export default function ArmsClipboard() {
  return (
    <g>
      {/* ── Left arm ── hanging straight down at the side */}
      <rect fill="var(--mascot-suit)" x={60} y={210} width={20} height={60} />
      <rect fill="var(--mascot-suit-hi)" x={60} y={210} width={10} height={40} />
      <rect fill="var(--mascot-skin)" x={60} y={270} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={60} y={280} width={20} height={10} />

      {/* ── Right arm ── bent forward across the body to hold the clipboard */}
      {/* upper arm dropping from the shoulder line */}
      <rect fill="var(--mascot-suit)" x={160} y={210} width={20} height={40} />
      <rect fill="var(--mascot-suit-hi)" x={170} y={210} width={10} height={30} />
      {/* forearm running horizontally across the body */}
      <rect fill="var(--mascot-suit)" x={120} y={240} width={60} height={20} />
      <rect fill="var(--mascot-suit-shadow)" x={120} y={250} width={60} height={10} />
      {/* hand gripping the underside of the clipboard */}
      <rect fill="var(--mascot-skin)" x={100} y={240} width={20} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={100} y={250} width={20} height={10} />

      {/* ── Clipboard ── board behind, paper in front, clip on top */}
      {/* board backing — neutral hardboard, literal hex (not a mascot color).
          This rect is drawn AFTER the forearm (x=120 y=240 w=60) and intentionally
          overpaints the inner portion of the forearm; only the strip of forearm to
          the right of the board's right edge (x=150) stays visible. If you resize
          either the board or the forearm rect, the amount of visible arm changes. */}
      <rect fill="#a89e8e" x={90} y={220} width={60} height={40} />
      {/* paper sheet — paper-white */}
      <rect fill="var(--canvas)" x={100} y={220} width={40} height={30} />
      {/* clip at the top of the board */}
      <rect fill="#a89e8e" x={110} y={210} width={20} height={10} />
      {/* ruled lines on the paper */}
      <rect fill="var(--mascot-skin-shadow)" x={100} y={230} width={40} height={10} />
    </g>
  );
}
