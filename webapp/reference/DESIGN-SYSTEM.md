# JLBC Website Revamp — Design System

Extracted from the approved homepage (`index.html`). This is the source of truth for
revamping every JLBC sub-page so they read as one coherent, modern civic application.

> **Constraint that defined everything:** HTML + CSS only. Almost no JavaScript — all interactivity
> (dropdowns, filters, toggles, sort) is done with `:hover`, `:focus-within`, and the `:checked`
> checkbox hack. The **only** JS is two self-contained search/filter islands: the Search page and the
> Fiscal Notes page's live filter (see §8). Every page must be previewable straight from `file://`.

---

## 1. Spirit / Design Intent

- **Authentic, not invented.** Uses the *real* JLBC navy wordmark (`jlbc-logo.png`) and the
  real Arizona State Legislature flag-burst logo (`azleg-logo.png`). Palette is the
  authentic JLBC navy, reworked into a disciplined **blue monochrome** — every red/orange/
  green/gold from the source site was remapped to cobalt / azure / steel / cerulean so the
  page feels calm, official, and modern without looking like a generic SaaS template.
- **Civic confidence.** Big, legible type (Nunito), generous rounding, soft layered shadows,
  lots of whitespace. Reads like a well-funded government product, not a brochure.
- **Photo-anchored hero (home).** A historic Arizona Capitol photochrome (`capitol-bg.jpg`)
  framed **top and bottom by thin navy bands**, with soft navy "blooms" pulling in from the
  left/right edges. The title is **centered**, with a **navy-tinted glass pill** directly below it
  ("Fiscal Policy Analysis for the Arizona State Legislature ★ azleg.gov" — the star is the
  divider). Three white gateway cards float up and overlap the lower band; the **center card is a
  live search box**, slightly wider + taller than its neighbours ("Overlap Cards" pattern, made
  search-forward 2026-06-15).
- **One row, no clutter.** The header is logo + inline menu + a **search icon button** that links
  straight to the search page (`subpage-search_jlbc.html`) — identical on **every** page, home
  included. It is a plain `<a>` button now, NOT the old CSS collapsing expand. The home page
  additionally shows the official-site notice as the in-hero pill instead of a separate gov strip.

---

## 2. Color Tokens (`:root`)

Copy this block verbatim into every sub-page's `<style>` so colors stay identical.

```css
:root {
  /* navy core — the JLBC brand */
  --navy:#2b2f63; --navy-700:#232752; --navy-900:#181b3d; --navy-100:#e7e8f2;
  /* accents — all blue-monochrome remaps of the source site's red/orange/green/gold */
  --az-red:#2f55c4;  --az-red-100:#e1e6fa;   /* was AZ flag red  -> cobalt   */
  --az-gold:#1b6fc4; --az-gold-d:#145aa6; --az-gold-100:#dceaf7; /* was gold -> azure */
  --copper:#3d6a99;  --copper-100:#e3ebf3;   /* was copper       -> steel    */
  --teal:#1782b3;    --teal-100:#dbeef8;     /* was teal/green   -> cerulean */
  /* ink + surfaces */
  --ink:#21243f; --ink-2:#4a4e6a; --ink-3:#757895;
  --line:#e6e6ef; --canvas:#f5f5fa; --card:#fff;
  /* shape + depth */
  --r-lg:22px; --r-md:16px; --r-sm:12px; --r-pill:999px; --gap:22px;
  --shadow:0 1px 2px rgba(27,27,61,.05),0 10px 26px rgba(27,27,61,.08);
  --shadow-sm:0 1px 2px rgba(27,27,61,.06),0 3px 10px rgba(27,27,61,.05);
  --maxw:1140px; --font:"Nunito","Segoe UI",system-ui,-apple-system,sans-serif;
}
```

**Accent usage rules**
- `--az-gold` (azure) = primary accent: active nav pill, primary CTA, hero metric accent bar.
  Always pair with `#fff` text — never dark text on azure.
- Category/status pills use the **darker** `-d` variant for text on a light `-100` tint so they
  stay AA-readable (e.g. `--az-gold-d` text on `--az-gold-100` background).
- Accent bars on cards rotate `a-gold` / `a-teal` / `a-red` for variety; meaning is not encoded
  in color — it's decorative rhythm.

---

## 3. Typography & Shape

- **Font:** Nunito (rounded humanist sans), `"Segoe UI"` / system fallback. `line-height:1.6`
  body, `1.2` headings. Headings are heavy: `font-weight:700–800`, slight negative tracking
  (`letter-spacing:-.5px`) on big numbers/titles.
- **Rounding scale:** `--r-lg:22px` (cards) · `--r-md:16px` (dropdowns, metric cards) ·
  `--r-sm:12px` (dropdown rows, small chips) · `--r-pill:999px` (nav items, pills, search).
- **Shadows:** two soft layered shadows only (`--shadow`, `--shadow-sm`). Never hard/black.
- **Container:** `.wrap { max-width:1140px; margin:0 auto; padding:0 22px; }`.

---

## 4. Layout Skeleton (every page reuses this)

```
[ header.site ]   sticky white: logo (left) · nav.primary (center, inline) · a SEARCH ICON BUTTON (right)
                  that links to the search page — on EVERY page incl. home (a plain <a>, not a collapsing
                  expand). Every page — home included — keeps a 3px navy-900 bottom border on the header
                  (unified 2026-06-16; the home header previously had none).
[ .gov ]          the old centered navy-900 strip. Used on NO pages now: sub-pages dropped it (2026-06-15),
                  and the home page replaced it with an in-hero navy-tinted PILL (`.gov-pill`, 2026-06-15).
[ page hero  ]    HOME = Capitol photo framed by two navy bands + side blooms; centered title; in-hero pill;
                  three Overlap gateway cards with the CENTER card = live search box.
                  SUB-PAGES = lighter title band (see §6).
[ main .wrap ]    content grid (home is 1fr / 340px; sub-pages may go single-column or 1fr/300px)
[ footer ]        navy: two-column .foot (JLBC name + description  |  CONTACT: phone · email, then a
                  Google-Maps-linked address below) + a .foot-bottom bar (© + mini JLBC logo, left;
                  Arizona State Legislature logo as a clickable outlink button, right).
```

The **header** and **footer** are shared chrome — copy them unchanged onto every page (the header's search
icon links to the search page on all of them). The header is now **identical on every page**, including the
3px navy-900 bottom border (unified 2026-06-16 — the home header used to omit it). The official-site notice
lives in the **home hero pill** (`.gov-pill`); sub-pages show neither the old `.gov` strip nor the pill. Only
the hero + main content change per page.

---

## 5. Reusable Components (lift these class blocks as-is)

| Component | Key classes | Notes |
|-----------|-------------|-------|
| Merged header | `header.site` `.head` `.logo` `nav.primary` `.nav-item` `.dropdown` | `nav.primary` is `flex-wrap:nowrap` + centered; dropdowns reveal on `:hover`/`:focus-within`. |
| Search button | `.search-icon-btn` (an `<a href="subpage-search_jlbc.html">`) | Round magnifier in the header that links straight to the search page; identical on every page. Replaced the CSS-only collapsing expand (`.search-toggle` / `.search-expand`) 2026-06-15 — that dead CSS is still present in sub-page `<style>` blocks but unused. |
| Active "home" pill | `.nav-item.active` + `.home-ic` | House SVG, azure pill, white icon — replaces the word "Home". |
| Hero pill (home) | `.gov-pill` `.azstar` | Navy-tinted glass pill in the home hero, below the title. The `.azstar` is the divider between the official-site notice and the `azleg.gov` link. Replaces the old `.gov` strip (no `.dot`). |
| Hero gateway cards (home) | `.m-cards` `.m-card` `.cardhead` `.a-gold/.a-teal/.a-red` `.search-card` `.search-field` | Three overlap cards; icon + title share a row (`.cardhead`). The center `.search-card` is a GET `<form>` to the search page (wider + taller than its siblings). |
| Hero image credit (home) | `.credit-toggle` (checkbox) `.credit-btn` (the small ⓘ at the hero's bottom-right) `.credit-modal` `.credit-card` | CSS-only popover (checkbox hack — the one `:checked` use left): clicking the translucent ⓘ shows a centered modal crediting the Arizona Memory Project source + "Modified with Gemini." |
| Footer | `footer.site` `.foot` `.fb` `.col` `.contact-row` `.line` `.foot-bottom` `.copyline` `.jlbc-mini` `.azleg-btn` `.foot-ext` | `.foot` is a flex two-column (JLBC info / Contact); `.contact-row` lays the phone+email and the Maps-linked address as horizontal rows; `.azleg-btn` is the bottom-right outlink button. |
| Metric card | `.m-cards` `.m-card` `.a-gold/.a-teal/.a-red` `.lbl/.num/.sub/.trend` | Left accent bar via `::before`; trend chip uses `--teal-100`. |
| Content card | `.card` `.head-row` `.ic` `.count` | Rounded `--r-lg` panel with icon + title + count chip header. The header→content divider is a **blue inset rounded line** (`--az-gold-100`, 2px, inset ~20px, rounded ends) drawn via `::after` — matches the accordion section dividers; replaced the old solid gray full-width border **site-wide** (2026-06-16). |
| Clickable update/meeting card (home) | `.upd-grid` `.upd-card` `.upd-band` `.upd-lbl` `.upd-date` `.upd-body` (+ `.mfh` / `.jccr` color modifiers) | Fully-clickable card: a tinted header band (category/committee + date) over a title + meta body; the **whole card** links to the document/agenda. Home "Budget & Revenue Updates" (navy / `.mfh` blue) and "Committee Meetings" (navy JLBC / `.jccr` teal) use these (2026-06-16). Replaced the legacy `.item`/`.stripe` feed rows and `.meeting`/`.cal`/`.info`/`.ag` rows (now unused on home). |
| List item (legacy) | `.item` `.stripe` `.ib` `.trow` `.pill` `.date` | Title left, category pill right via `.trow` flex. Superseded on the home page by the clickable cards above; still defined in CSS. |
| Sidebar quick-links / promo | `.card` variants | Right column on home. |

**Pills:** `.pill` always carries a mini inline `<svg>` (12px) and sits to the *right* of the
item title via `.trow { justify-content:space-between }`. There is **no** separate square doc
icon — that was removed during design review.

---

## 6. Sub-page Hero — LOCKED (`.subhero`)

A shallow Capitol-photo band: the **same** `capitol-bg.jpg` as home (brand continuity) but
~half height and a heavier navy overlay so it reads clearly as a secondary page, not a second
front door. Contents, top to bottom:
- page title (`<h1>`, `clamp(24px,3.2vw,34px)`, weight 800) — kept to a single line
- a TWO-LINE description (`.lead`, max ~66ch, `line-height:1.5`): `min-height:3em` reserves two
  lines even for short copy and `-webkit-line-clamp:2` caps longer copy at two, so the block is
  always exactly two lines tall. **Rewrite over-long descriptions** rather than letting the clamp
  ellipsis them mid-sentence.
- a row of 2–3 summary chips (`.chip` — translucent white pill + azure-tinted icon) stating the
  page's shape (e.g. "Published monthly", "FY 2026–1984"). The `.chips` row has a reserved
  `min-height`, and **every** sub-page carries one (the search page included).

**Fixed height (2026-06-15):** because the title is one line, the lead reserves two lines, and the
chip row is reserved, every `.subhero` is the SAME height across all sub-pages. Don't ship a sub-page
hero missing the lead or the chip row, and don't let a description run to three lines — that breaks the
uniformity. The home hero is intentionally taller/different.

**No breadcrumb.** (Removed 2026-06-14 per Destin.) The user's location is shown by the
**active top-nav highlight** instead — see §8 rule. Reference implementation:
`subpage-monthly-fiscal-highlights.html`.

---

## 7. Files in this folder

| File | Role |
|------|------|
| `index.html` | Approved homepage (was `azjlbc-overlap-merged.html`). Source of truth. |
| `jlbc-logo.png` | Real JLBC navy wordmark. Header logo. |
| `azleg-logo.png` | Real AZ State Legislature flag-burst logo. Used as the footer's bottom-right outlink button (and in the home-page gov strip's link). |
| `jlbc-logo.png` (footer) | Also reused as the mini logo beside the footer copyright (`.jlbc-mini`). |
| `capitol-bg.jpg` | Historic AZ Capitol photochrome, home hero background. **Large — compress before any real deployment** (target <400 KB WebP/JPEG). |
| `DESIGN-SYSTEM.md` | This file. |
| `SUBPAGES.md` | Sub-page inventory + revamp tracker (next phase). |

---

## 8. Conventions for building sub-pages

1. Start from a copy of an existing **sub-page**, NOT `index.html` — the home **hero** differs (centered
   hero with an in-card search box + an in-hero pill + three Overlap gateway cards). The **header** itself is
   now identical on home and sub-pages (same search-icon button, same 3px navy bottom border).
   Keep `:root`, `header.site`, and `footer` untouched. Sub-pages have no `.gov` strip and no hero pill.
2. Swap the hero for the sub-page title band (§6) and replace `main` content.
3. **Location is shown in the nav rail.** Mark the top-level nav item the page lives under
   `.active` (azure pill) instead of Home. For a page reached through a dropdown (e.g. Tax
   Handbook under State Revenues), make the **parent** top-level item active. This is the only
   wayfinding cue — there is no breadcrumb.
4. **Sidebar is NOT sticky** (`.side .card{position:static}`). The whole page scrolls as one so
   content never slides underneath a pinned bubble. (Changed 2026-06-14 per Destin.)
5. **Minimize public-records references.** JLBC lacks staff to process many requests, so do NOT
   put "Public Records Portal" CTAs in promos/sidebars. Keep exactly one link — the
   "Public Records Request Portal" item in the About dropdown (legally required) — and nothing more.
6. Keep all outlinks pointing at the real azleg.gov / azjlbc.gov URLs (fake-but-plausible is fine
   for internal links until the full set is mapped).
7. One row of nav, always. Never let the menu wrap on desktop.
8. Almost no JavaScript. If something needs interactivity, solve it with `:checked` / `:hover` /
   `:focus-within` (the header search is now a plain link to the search page, so the old collapsing-search
   `:checked` hack is gone). There are **two** deliberate, self-contained JS exceptions: the **Search page**
   (`subpage-search_jlbc.html`) and the **Fiscal Notes page** (`subpage-fiscal-notes.html`) — its sidebar
   does live bill-number/keyword filtering plus a "search all sessions" scope toggle that CSS can't express.
   Everything else on Fiscal Notes (chamber switch, session filter, sort, the toggle pill's checked state)
   is still pure CSS. That page is **generated** by `fiscal-notes-build/` (see its `BUILD.md`) — don't
   hand-edit `subpage-fiscal-notes.html`. The **Ballot Initiatives** page (`subpage-ballot-initiatives.html`)
   is ALSO generated — by `ballot-build/` — though it stays pure CSS (no JS island): edit
   `ballot-build/base.html` (chrome) or `build.py` (the 107-proposition data table) and rebuild, never the output.
10. **Accordions start COLLAPSED — no `checked` on `.acc-toggle`.** Collapsible sections use the checkbox
    hack (`.acc-toggle` + `:checked` label). A page must NOT ship any `.acc-toggle` with the `checked`
    attribute (that auto-expands a row on load, which we don't want). NOTE: this does NOT apply to the
    `.era-radio` filter group — its "All" radio keeps `checked` so the default filter view is correct.
9. **Sidebar order: the blue promo sits ABOVE the "Related Pages" card, and its link is never duplicated in
   that list.** Each sub-page sidebar is `<aside class="side">` → `.promo` (navy card, the single blue CTA)
   THEN the `.card` "Related Pages" list. The promo CTA's target must not also appear as a `.qlink` in
   Related Pages — if it would, drop it from the list (deduped site-wide 2026-06-15). Because the promo is
   now the FIRST sidebar item, its rule is `.promo{margin:0 0 var(--gap)}` (top-aligned with the main
   content, gap BELOW before the card) — NOT the old `margin-top` (which left it pushed down and touching
   the card). The home `.promo` keeps `margin-top` since it still sits below Quick Links.
