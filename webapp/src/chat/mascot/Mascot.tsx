// Mascot — composes the shared MascotBody with one of six swappable arm sets
// into a sized <svg>, and drives the idle animation. The bob is pure CSS
// (`.mascot-animate`, in the `/* ===== chat ===== */` block of app.css); blink
// and push-glasses are JS-driven here because their timing is randomized and
// CSS cannot randomize.
//
// Ported from web/components/mascot/Mascot.tsx. Behavior is unchanged; the
// only edits are the dropped "use client" directive (no RSC in this SPA) and
// React.JSX.Element -> JSX-free typing for React 18.

import { useEffect, useState, type ReactElement } from "react";

import { MASCOT_DIMENSIONS, type MascotPose, type MascotSize } from "./types.js";
import MascotBody from "./MascotBody.js";
import ArmsSides from "./poses/ArmsSides.js";
import ArmsClasped from "./poses/ArmsClasped.js";
import ArmsWave from "./poses/ArmsWave.js";
import ArmsCrossed from "./poses/ArmsCrossed.js";
import ArmsClipboard from "./poses/ArmsClipboard.js";
import ArmsHips from "./poses/ArmsHips.js";
import ArmsPushingGlasses from "./poses/ArmsPushingGlasses.js";
import GlassesUp from "./poses/GlassesUp.js";

const POSE_COMPONENTS: Record<MascotPose, () => ReactElement> = {
  sides: ArmsSides,
  clasped: ArmsClasped,
  wave: ArmsWave,
  crossed: ArmsCrossed,
  clipboard: ArmsClipboard,
  hips: ArmsHips,
};

// Poses whose arms hang/rest low enough that swapping in the raised
// push-glasses arm reads cleanly. wave/crossed already have raised or
// occupied arms, so the push-glasses moment is skipped for them.
const PUSH_GLASSES_POSES: ReadonlySet<MascotPose> = new Set<MascotPose>([
  "clasped",
  "clipboard",
  "sides",
  "hips",
]);

interface Props {
  pose: MascotPose;
  size?: MascotSize;
  /** Idle bob + blink + push-glasses. Default true. */
  animate?: boolean;
  className?: string;
}

export default function Mascot({
  pose,
  size = "hero",
  animate = true,
  className,
}: Props) {
  const { width, height } = MASCOT_DIMENSIONS[size];

  const [blink, setBlink] = useState(false);
  const [pushGlasses, setPushGlasses] = useState(false);

  // -- Blink -- fires for ~150ms at a random 3-6s gap. ----------------------
  useEffect(() => {
    if (!animate) return;
    // The tests render this through renderToString, where effects never run,
    // and jsdom has no matchMedia — hence both guards.
    if (
      typeof window === "undefined" ||
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    )
      return;
    // Track BOTH the schedule timer and the inner 150ms blink-off timer so
    // cleanup leaves nothing running — otherwise an unmount mid-blink would
    // try to setState on an unmounted component.
    let scheduleTimer: ReturnType<typeof setTimeout>;
    let offTimer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      const gap = 3000 + Math.random() * 3000;
      scheduleTimer = setTimeout(() => {
        setBlink(true);
        offTimer = setTimeout(() => setBlink(false), 150);
        schedule();
      }, gap);
    };
    schedule();
    return () => {
      clearTimeout(scheduleTimer);
      clearTimeout(offTimer);
    };
  }, [animate]);

  // -- Push glasses -- fires for ~700ms at a random 15-25s gap, only for the
  //    low-arm poses (wave/crossed are skipped — their arms are already up). --
  const canPushGlasses = PUSH_GLASSES_POSES.has(pose);
  useEffect(() => {
    if (!animate) return;
    if (!canPushGlasses) return;
    if (
      typeof window === "undefined" ||
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    )
      return;
    // Same dual-timer cleanup pattern as blink: clear the schedule timer AND
    // the inner 700ms reset timer on unmount / pose change.
    let scheduleTimer: ReturnType<typeof setTimeout>;
    let offTimer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      const gap = 15000 + Math.random() * 10000;
      scheduleTimer = setTimeout(() => {
        setPushGlasses(true);
        offTimer = setTimeout(() => setPushGlasses(false), 700);
        schedule();
      }, gap);
    };
    schedule();
    return () => {
      clearTimeout(scheduleTimer);
      clearTimeout(offTimer);
      // If we unmount / change pose mid-moment, drop the raised arm so the
      // next render of this pose starts from the resting arm set.
      setPushGlasses(false);
    };
  }, [animate, canPushGlasses]);

  // While the push-glasses moment is active, swap in the raised arm set;
  // otherwise the normal pose arms. Lookup always resolves.
  const showPush = pushGlasses && canPushGlasses;
  const Arms = showPush ? ArmsPushingGlasses : POSE_COMPONENTS[pose];

  return (
    <svg
      viewBox="0 0 240 420"
      width={width}
      height={height}
      role="img"
      aria-label="JLBC budget assistant"
      data-blink={blink ? "true" : undefined}
      className={["mascot", animate ? "mascot-animate" : "", className ?? ""]
        .filter(Boolean)
        .join(" ")}
      style={{ shapeRendering: "crispEdges" }}
    >
      <MascotBody />
      <Arms />
      {/* GlassesUp overlays the body's resting glasses, drawing them shifted
          up one cell while the hand reaches them. */}
      {showPush && <GlassesUp />}
    </svg>
  );
}
