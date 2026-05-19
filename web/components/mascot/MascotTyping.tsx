"use client";

// Seated working-loop scene — ported verbatim from web/app/mascot-sit/page.tsx.
// Mascot parts use var(--mascot-*) CSS variables; chair/laptop keep literal hex.
// See the throwaway page for geometry/animation rationale.

// Chair and laptop literal-hex palette (props, not the themed mascot).
const C = {
  metal: "#5a5f66",
  metalHi: "#888d94",
  metalShadow: "#3a3e44",
  silver: "#c8ccd0",
  silverDark: "#6a6e74",
};

/* ── Keyframe generation ──────────────────────────────────────────────────
 * One 12s master loop. Typing fills 0–64%; 64–100% is the pause (hands
 * still, head looks up to think, then back down). steps(1,end) timing
 * makes every segment a hold-then-snap, so the motion stays pixel-crisp. */
const LOOP_MS = 12000;

function handFrames(startDown: boolean): string {
  let s = "";
  const half = 2.7; // % of loop per half-tap
  let down = startDown;
  for (let p = 0; p < 64; p += half) {
    s += `${p.toFixed(1)}%{transform:translate(0,${down ? 4 : 0}px)}`;
    down = !down;
  }
  // hands rest flat through the whole pause
  s += `64%{transform:translate(0,0)}100%{transform:translate(0,0)}`;
  return s;
}

function headFrames(): string {
  let s = "";
  // gentle nod while typing
  let down = false;
  for (let p = 0; p < 64; p += 8) {
    s += `${p}%{transform:translate(0,${down ? 3 : 0}px)}`;
    down = !down;
  }
  // look up · hold · a small ponder shift · hold · look back down
  s += `64%{transform:translate(0,0)}`;
  s += `67%{transform:translate(0,-7px)}`;
  s += `77%{transform:translate(0,-7px)}`;
  s += `81%{transform:translate(3px,-5px)}`;
  s += `88%{transform:translate(0,-7px)}`;
  s += `93%{transform:translate(0,-7px)}`;
  s += `95%{transform:translate(0,0)}`;
  s += `100%{transform:translate(0,0)}`;
  return s;
}

const KEYFRAMES = `
  @keyframes workHandNear{${handFrames(true)}}
  @keyframes workHandFar{${handFrames(false)}}
  @keyframes workHead{${headFrames()}}
  .work-hand-near{animation:workHandNear ${LOOP_MS}ms steps(1,end) infinite;}
  .work-hand-far{animation:workHandFar ${LOOP_MS}ms steps(1,end) infinite;}
  .work-head{animation:workHead ${LOOP_MS}ms steps(1,end) infinite;}
`;

/* ── SHARED side-profile head + cap + glasses (faces RIGHT). ── */
function SideHead({ hx, hy }: { hx: number; hy: number }) {
  const X = (n: number) => n - 60 + hx;
  const Y = (n: number) => n - 30 + hy;
  return (
    <g>
      <rect fill="var(--mascot-cap)" x={X(60)} y={Y(30)} width={110} height={60} />
      <rect fill="var(--mascot-cap)" x={X(50)} y={Y(50)} width={10} height={40} />
      <rect fill="var(--mascot-cap-hi)" x={X(60)} y={Y(30)} width={110} height={10} />
      <rect fill="var(--mascot-cap-hi)" x={X(70)} y={Y(20)} width={90} height={10} />
      <rect fill="var(--mascot-cap)" x={X(160)} y={Y(80)} width={40} height={10} />
      <rect fill="var(--mascot-brim)" x={X(160)} y={Y(90)} width={50} height={10} />
      <rect fill="var(--mascot-skin)" x={X(60)} y={Y(90)} width={110} height={80} />
      <rect fill="var(--mascot-skin)" x={X(50)} y={Y(100)} width={10} height={60} />
      <rect fill="var(--mascot-skin)" x={X(170)} y={Y(120)} width={10} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={X(60)} y={Y(90)} width={110} height={10} />
      <rect fill="var(--mascot-skin-hi)" x={X(150)} y={Y(140)} width={10} height={20} />
      <rect fill="var(--mascot-skin-shadow)" x={X(160)} y={Y(150)} width={10} height={10} />
      <rect fill="var(--mascot-skin-shadow)" x={X(60)} y={Y(170)} width={100} height={10} />
      <text
        fill="var(--canvas)"
        x={X(115)}
        y={Y(64)}
        textAnchor="middle"
        fontFamily="monospace"
        fontWeight="bold"
        fontSize={18}
      >
        JLBC
      </text>
      <rect fill="var(--mascot-suit-hi)" x={X(142)} y={Y(100)} width={36} height={6} />
      <rect fill="var(--mascot-suit)" x={X(80)} y={Y(128)} width={62} height={4} />
      <circle fill="var(--mascot-skin)" cx={X(160)} cy={Y(130)} r={19} />
      <circle fill="none" stroke="var(--mascot-suit)" strokeWidth={3.5} cx={X(160)} cy={Y(130)} r={19} />
      <circle fill="var(--mascot-suit)" cx={X(160)} cy={Y(130)} r={8} />
      <rect fill="var(--canvas)" x={X(163)} y={Y(123)} width={4} height={4} />
    </g>
  );
}

/* ── Laptop — keyboard deck shortened slightly (80px wide, 4 keys). ── */
function Laptop() {
  const bx = 138, by = 246, deckW = 80, screenW = 24, screenH = 72;
  const screenX = bx + deckW - screenW;
  const screenY = by - screenH;
  return (
    <g>
      <rect fill={C.silver} x={bx} y={by} width={deckW} height={12} />
      <rect fill={C.silverDark} x={bx} y={by + 12} width={deckW} height={6} />
      <g fill={C.silverDark}>
        {[0, 1, 2, 3].map((i) => (
          <rect key={i} x={bx + 8 + i * 15} y={by + 4} width={11} height={4} />
        ))}
      </g>
      <rect fill={C.silverDark} x={screenX + screenW - 6} y={screenY} width={6} height={screenH + 2} />
      <rect fill={C.silver} x={screenX} y={screenY} width={screenW} height={screenH + 2} />
      <rect fill="var(--mascot-cap)" x={screenX - 2} y={screenY + 6} width={screenW} height={screenH - 10} />
      {[0, 1, 2, 3].map((i) => (
        <rect key={i} fill="var(--canvas)" x={screenX} y={screenY + 14 + i * 8} width={i % 2 ? 18 : 14} height={3} />
      ))}
      <rect className="mascot-typing-cursor" fill="var(--canvas)" x={screenX} y={screenY + 14 + 4 * 8} width={4} height={6} />
    </g>
  );
}

function Chair() {
  return (
    <g>
      <rect fill={C.metal} x={70} y={182} width={26} height={118} />
      <rect fill={C.metalHi} x={70} y={182} width={26} height={10} />
      <rect fill={C.metalShadow} x={70} y={182} width={8} height={118} />
      <rect fill={C.metal} x={96} y={250} width={12} height={40} />
      <rect fill={C.metal} x={84} y={290} width={150} height={22} />
      <rect fill={C.metalHi} x={84} y={290} width={150} height={6} />
      <rect fill={C.metalShadow} x={84} y={306} width={150} height={6} />
      <rect fill={C.metalShadow} x={146} y={312} width={20} height={40} />
      <rect fill={C.metal} x={150} y={312} width={6} height={40} />
      <rect fill={C.metal} x={88} y={350} width={140} height={12} />
      <rect fill={C.metalShadow} x={88} y={360} width={140} height={6} />
      <rect fill={C.metalShadow} x={88} y={364} width={20} height={10} />
      <rect fill={C.metalShadow} x={148} y={364} width={20} height={10} />
      <rect fill={C.metalShadow} x={208} y={364} width={20} height={10} />
    </g>
  );
}

function Legs() {
  return (
    <g>
      <rect fill="var(--mascot-suit)" x={94} y={264} width={140} height={26} />
      <rect fill="var(--mascot-suit-hi)" x={94} y={264} width={140} height={7} />
      <rect fill="var(--mascot-suit)" x={208} y={290} width={26} height={50} />
      <rect fill="var(--mascot-suit-shadow)" x={208} y={290} width={7} height={50} />
      <rect fill="var(--mascot-suit-shadow)" x={206} y={336} width={48} height={16} />
    </g>
  );
}

function Torso() {
  return (
    <g>
      <rect fill="var(--mascot-suit)" x={94} y={166} width={70} height={124} />
      <rect fill="var(--mascot-suit-shadow)" x={94} y={166} width={10} height={124} />
      <rect fill="var(--mascot-suit-hi)" x={154} y={166} width={10} height={80} />
    </g>
  );
}

function Head() {
  return (
    <g>
      <rect fill="var(--mascot-skin)" x={111} y={146} width={36} height={30} />
      <SideHead hx={74} hy={0} />
    </g>
  );
}

/* Rear arm — drawn behind, darker. Brought in close behind the front hand
 * (the two hands pair up over the keyboard, as a side view should). */
function FarArm() {
  return (
    <g>
      <rect fill="var(--mascot-suit-shadow)" x={146} y={210} width={34} height={15} />
      <rect fill="var(--mascot-skin-shadow)" x={166} y={223} width={16} height={5} />
      <rect fill="var(--mascot-skin-shadow)" x={162} y={228} width={24} height={14} />
      <rect fill="var(--mascot-skin-shadow)" x={157} y={230} width={6} height={10} />
      <rect fill="var(--mascot-suit-shadow)" x={162} y={238} width={24} height={4} />
    </g>
  );
}

/* Front arm — drawn on top. */
function NearArm() {
  return (
    <g>
      <rect fill="var(--mascot-suit)" x={146} y={214} width={44} height={18} />
      <rect fill="var(--mascot-suit-hi)" x={146} y={214} width={44} height={7} />
      <rect fill="var(--mascot-suit-shadow)" x={182} y={214} width={8} height={18} />
      <rect fill="var(--mascot-skin)" x={186} y={228} width={16} height={5} />
      <rect fill="var(--mascot-skin)" x={182} y={233} width={24} height={14} />
      <rect fill="var(--mascot-skin)" x={177} y={235} width={6} height={10} />
      <rect fill="var(--mascot-skin-shadow)" x={182} y={243} width={24} height={4} />
    </g>
  );
}

export default function MascotTyping() {
  return (
    <svg
      viewBox="0 -20 360 410"
      role="img"
      aria-label="JLBC budget assistant — searching"
      className="mascot-typing"
      style={{ shapeRendering: "crispEdges" }}
    >
      <style>{KEYFRAMES}</style>
      <Chair />
      <Legs />
      <Torso />
      <Laptop />
      <g className="work-head">
        <Head />
      </g>
      <g className="work-hand-far">
        <FarArm />
      </g>
      <g className="work-hand-near">
        <NearArm />
      </g>
    </svg>
  );
}
