import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "vitest";

// 🔴 WHY A STYLESHEET TEST AT ALL. Four of the seven findings fixed on
// 2026-08-16 were things the product owner could SEE and no test could:
// Approve rendering lighter than the "not now" text beside it, a format name
// wrapping onto two lines, "None published" dropping under every address, and
// two different caret shapes on one card. jsdom applies no stylesheet, so a
// rendering test cannot reach any of them — which is exactly how they shipped
// green in the first place.
//
// What this CAN do is pin the DECLARATIONS, so a later edit that undoes one has
// to do it deliberately. What it CANNOT do is tell anyone how the page looks;
// that still needs eyes on a browser, and this file must never be cited as if
// it had checked appearance. Same idiom, and the same limit, as
// `chat/__tests__/chat-css-contract.test.ts` and
// `components/header-css-contract.test.ts`.

const CSS = readFileSync(resolve(__dirname, "../../styles/app.css"), "utf8");

/** The declaration block of one selector, whitespace-collapsed. */
function rule(selector: string): string {
  const at = CSS.indexOf(`${selector}{`);
  expect(at, `no rule for ${selector}`).toBeGreaterThan(-1);
  return CSS.slice(at + selector.length + 1, CSS.indexOf("}", at)).replace(/\s+/g, "");
}

test("Approve is the FILLED primary, and only inside the approve row", () => {
  // It was a white pill with a gold border — the shared `.allbtn` — sitting
  // beside plain text controls, so the one control in this row that WRITES to
  // the share (and changes what every analyst's "Full report" button
  // downloads) read as lighter than its neighbours.
  const filled = rule(".page-upload .up-rl-acts .allbtn");
  expect(filled).toContain("background:var(--navy)");
  expect(filled).toContain("color:#fff");

  // 🔴 And the shared primitive is UNCHANGED. `Add` and `Preview` on the card
  // above are correctly secondary; painting `.allbtn` itself would repaint
  // them and undo the hierarchy this fixes.
  expect(rule(".page-upload .allbtn")).toContain("background:#fff");
});

test("a format's name cannot wrap, because it has a line to itself", () => {
  // Reported as wrapping at a fixed 96px column. Widening it was the first
  // answer — and then both formats were renamed to the words the ANALYST sees
  // on the "Full report" chooser, and "Linked Table of Contents" (~168px at
  // 13px/800) leaves too little of the ~586px row for a filename, a size, an
  // opener and two controls. So the name takes its own line and can never be a
  // few pixels from wrapping again.
  const k = rule(".page-upload .up-rl-k");
  expect(k).toContain("flex:1 0 100%".replace(/\s+/g, ""));
  expect(k).toContain("white-space:nowrap");
});

test("the opener and the mini controls are ONE right-aligned cluster", () => {
  // "None published" was dropping onto a line of its own under every address,
  // making each format two rows tall — the controls were direct flex children,
  // so a long filename could split them. It stays VISIBLE rather than moving
  // behind "change": six Appropriations Report editions genuinely have no
  // single file, and burying the right answer two clicks deep is worse.
  const ctl = rule(".page-upload .up-rl-ctl");
  expect(ctl).toContain("margin-left:auto");
  expect(ctl).toContain("flex:none");
});

test("nothing in the report-link row is a bare underlined blue link", () => {
  // Destin, 2026-08-16: the hyperlink look is out. `open ↗` stays a real <a>
  // with target/rel and its own per-format accessible name — only its LOOK is
  // the page's existing `.fchip` pill, copied rather than re-derived.
  const open = rule(".page-upload .up-rl-open");
  expect(open).toContain("text-decoration:none");
  expect(open).toContain("border-radius:var(--r-pill)");
  expect(open).not.toContain("text-decoration:underline");
});

test("there is ONE caret shape on this page", () => {
  // The section rows drew a CSS border-triangle while the card headers drew a
  // stroked SVG chevron. The triangle's rules are gone, and the rotation rule
  // is now generic over `.up-disclose`, so a new disclosure gets the right
  // caret by default instead of needing to remember which one to copy.
  expect(CSS).not.toContain(".up-disclose-mark{");
  expect(CSS).toContain(".page-upload .up-disclose[open]>summary .up-card-caret{");
});

test("'a link is waiting' is amber, and is NOT the failure colour", () => {
  // The mockup's `.chip.need`. `up-tone-warn` is spent on "can't check", a
  // FAILURE, and this palette remaps `--az-red` to a blue anyway — work
  // waiting and a check that broke must not share a colour. `--warn`
  // (#b45309) was chosen at 5.9:1 for this kind of use.
  expect(rule(".page-upload .up-tone-need")).toContain("color:var(--warn)");
  expect(rule(".page-upload .up-tone-warn")).not.toContain("var(--warn)");
});
