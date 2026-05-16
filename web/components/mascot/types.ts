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

/** Render size. hero = welcome screen, chip = header/nook, tiny = inline. */
export type MascotSize = "hero" | "chip" | "tiny";

/** Pixel dimensions per size. The SVG viewBox is always 0 0 240 320. */
export const MASCOT_DIMENSIONS: Record<MascotSize, { width: number; height: number }> = {
  hero: { width: 240, height: 320 },
  chip: { width: 40, height: 54 },
  tiny: { width: 24, height: 32 },
};
