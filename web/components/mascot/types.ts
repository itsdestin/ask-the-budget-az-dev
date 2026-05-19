// Shared types for the JLBC mascot component family. See
// docs/superpowers/specs/2026-05-15-ui-prettify-mascot-design.md §2.

/** Front-view poses — each is a swappable arm set over the shared body. */
export type MascotPose =
  | "sides"
  | "clasped"
  | "wave"
  | "crossed"
  | "clipboard"
  | "hips";

/** Render size. hero = welcome screen, small = left-column avatar, chip = legacy header/nook, tiny = inline. */
export type MascotSize = "hero" | "small" | "chip" | "tiny";

/** Pixel dimensions per size. The SVG viewBox is always 0 0 240 420. */
export const MASCOT_DIMENSIONS: Record<MascotSize, { width: number; height: number }> = {
  hero: { width: 240, height: 420 },
  // small — persistent left-column avatar in Layout B (has-messages). Proportional to hero's 240×420 viewBox.
  small: { width: 120, height: 210 },
  chip: { width: 40, height: 70 },
  tiny: { width: 24, height: 42 },
};
