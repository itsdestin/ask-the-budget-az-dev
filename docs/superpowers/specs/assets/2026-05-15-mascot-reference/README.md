# Mascot reference mockups — 2026-05-15

Approved visual mockups from the brainstorm session behind
[`../../2026-05-15-ui-prettify-mascot-design.md`](../../2026-05-15-ui-prettify-mascot-design.md).
These HTML files hold the **canonical pixel-art SVG geometry** for the JLBC mascot —
every rect coordinate was tuned here. The implementation plan
(`docs/superpowers/plans/2026-05-15-ui-prettify-mascot.md`) ports these into React
components. They are committed because the brainstorm working directory
(`.superpowers/`) is gitignored and would otherwise be lost.

Open any file directly in a browser to see the rendered, animated mockup.

| File | What it is | Authoritative for |
|---|---|---|
| `palette.html` | Three palette options | The chosen "Paper & Civic Blue" palette (card `paper-sky`) |
| `mascot-pixel-poses.html` | Six P3 civic-warm poses | `MascotBody` + all six `Arms*` pose components. Symbols: `#body`, `#arms-sides`, `#arms-clasped`, `#arms-wave`, `#arms-crossed`, `#arms-clipboard`, `#arms-hips` |
| `typing-side-v6-lid-angles.html` | Six lid angles | The side-typing scene — **card D ("Comfortable ~110°")** is the approved one. Symbols: `#m-body`, `#base-sleek`, `#hand` + card D's lid polygons |
| `typing-side-present-v2.html` | Side↔front cycle | The `#front-presenting` symbol (the MascotPresenting scene) |
| `idle-moments.html` | Idle-moment menu | The `blink` and `glasses` (push-up-glasses) frame swaps — symbols `#eye-pair-fwd`, `#eye-pair-shut`, `#arms-pushing`, `#glasses-up`, etc. |
| `welcome-hero.html` | Three welcome layouts | **Layout A ("Centered stack")** — the approved welcome hero. Has the `#mascot-wave` symbol |
| `conversation-chrome.html` | Conversation states | The three chrome states (answer / thinking / refusal); symbols `#m-clipboard`, `#m-crossed`, `#side-typing` |

Note: the mockups use literal hex colors and inline `<style>` for the companion's
constraints. The React components must instead read the `--mascot-*` CSS variables
from `globals.css` (spec §2). The hex values in the mockups are the source values for
those variables.
