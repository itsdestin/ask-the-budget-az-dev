// JLBC site search — fully self-contained semantic search.
// CLASSIC script (not an ES module) so it also loads from file://, where module scripts are blocked.
// Over HTTP (the real deployment) it DYNAMICALLY imports a small embedding model + int8 vectors,
// embeds the query in the browser, and ranks by cosine blended with a keyword signal. From file://
// it falls back to keyword-only over the same metadata. Nothing leaves the browser either way.

// Paths are resolved against the PAGE (site root), so include the assets/search/ prefix.
const ASSET = 'assets/search/';
let pipeline = null; // loaded on demand (semantic path only, HTTP)

const docs = window.JLBC_DOCS || [];
// Semantic mode (dynamic import + fetch of the model/WASM) only works over http(s). Treat EVERYTHING
// else — file://, about:srcdoc (the single-file site bundle's iframe), blob: — as "file-like" so it
// uses the keyword fallback instead of trying (and failing) to import the model.
const isFile = !/^https?:$/.test(location.protocol);

const $ = s => document.querySelector(s);
const form = $('#searchForm'), input = $('#q');
const statusEl = $('#status'), modeNote = $('#modeNote');
const resultsCard = $('#resultsCard'), resultsEl = $('#results'),
      resultsCount = $('#resultsCount'), introCard = $('#introCard');
const typeWrap = $('#typeFilters'), yearSel = $('#yearFilter');

let extractor = null, vecIndex = null, semanticReady = false;
const activeTypes = new Set();
// TOP-LINE document count shown on the page. Computed in buildFilters() as the sum of every filter
// category (reports collapsed to one-per-year; per-agency book pages + summary sections NOT counted
// individually). Defaults to docs.length until buildFilters runs. See buildFilters for the rationale.
let topLineCount = docs.length;

const setStatus = (m, err) => { statusEl.innerHTML = err ? `<span class="err">${m}</span>` : m; };

// ---------- report families ----------
// A Baseline / Appropriations annual report is published as MANY docs (whole-book variants + a per-agency
// page per agency + statewide summary sections). They all belong to ONE report. `familyOf` collapses
// them so (a) the filter chip counts a report ONCE (not once per sub-page) and (b) search results group
// under their report. Everything else (fiscal notes, tax handbook, meetings…) stands alone.
function familyOf(d) {
  if (/baseline/i.test(d.doc_type)) return 'Baseline';
  if (/appropriat/i.test(d.doc_type)) return 'Appropriations Report';
  return null;
}

// ---------- filter buckets ----------
// The filter chips are a CURATED, FIXED set (not one chip per raw doc_type — that produced ~26 chips).
// Every document maps to exactly ONE bucket; anything that isn't one of the named families lands in
// "Other". The two report families still collapse their per-agency sub-pages, so their chip counts are
// distinct-annual-reports, not raw page totals (see buildFilters). Displayed in this exact order.
const BUCKET_ORDER = ['Fiscal Notes', 'Agency Budget Requests', 'Appropriations Reports', 'Tax Handbooks',
  'Baseline Books', 'Annual Financial Reports', 'Executive Budget', 'Other'];
const REPORT_BUCKETS = new Set(['Baseline Books', 'Appropriations Reports']); // collapse sub-pages by year
function bucketOf(d) {
  const fam = familyOf(d);
  if (fam === 'Baseline') return 'Baseline Books';
  if (fam === 'Appropriations Report') return 'Appropriations Reports';
  if (d.doc_type === 'Fiscal Notes') return 'Fiscal Notes';
  if (d.doc_type === 'Agency Budget Request') return 'Agency Budget Requests';
  if (d.doc_type === 'Tax Handbook' || d.category === 'Tax Handbook') return 'Tax Handbooks';
  if (d.doc_type === 'Annual Financial Report' || d.category === 'Annual Financial Report') return 'Annual Financial Reports';
  if (d.category === 'Executive Budget') return 'Executive Budget'; // exec State Agency Detail + State Funds
  return 'Other';
}

// ---------- filters UI ----------
(function buildFilters() {
  // The page ships pre-rendered fallback chips + year <option>s inside #typeFilters / #yearFilter so the
  // filter row isn't empty if this script fails to load. When it DOES run we rebuild from the live index,
  // so clear the static fallbacks first — otherwise every chip and year renders TWICE (the duplicate-
  // filters bug). Keep the year <select>'s first option ("All years"); drop the rest.
  typeWrap.innerHTML = '';
  while (yearSel.options.length > 1) yearSel.remove(1);

  const years = new Set();
  const raw = {};        // non-report bucket -> raw doc count
  const repYears = {};   // report bucket -> Set of distinct fiscal years (so a report counts once)
  for (const d of docs) {
    if (d.fiscal_year) years.add(d.fiscal_year);
    const b = bucketOf(d);
    if (REPORT_BUCKETS.has(b)) { (repYears[b] = repYears[b] || new Set()).add(d.fiscal_year); }
    else { raw[b] = (raw[b] || 0) + 1; }
  }
  // report buckets count distinct annual reports (per-agency sub-pages collapse); others count raw docs
  const countFor = b => REPORT_BUCKETS.has(b) ? (repYears[b] ? repYears[b].size : 0) : (raw[b] || 0);
  // TOP-LINE total = sum across ALL buckets. This is the "N documents indexed" headline — NOT
  // docs.length (~5,854), which counts each Baseline/Appropriations per-agency page and each summary
  // section separately. Because the headline is the sum of the chips, the number a user sees always
  // equals the sum of the categories they can filter by.
  topLineCount = BUCKET_ORDER.reduce((a, b) => a + countFor(b), 0);
  // render the curated buckets in BUCKET_ORDER (skip any that are empty)
  BUCKET_ORDER.forEach(b => {
    const n = countFor(b);
    if (!n) return;
    const c = document.createElement('button');
    c.className = 'fchip'; c.type = 'button'; c.textContent = `${b} (${n})`; c.dataset.type = b;
    c.addEventListener('click', () => {
      c.classList.toggle('on');
      c.classList.contains('on') ? activeTypes.add(b) : activeTypes.delete(b);
      if (input.value.trim()) run(input.value.trim());
    });
    typeWrap.appendChild(c);
  });
  [...years].sort((a, b) => b - a).forEach(y => {
    const o = document.createElement('option'); o.value = y; o.textContent = 'FY ' + y; yearSel.appendChild(o);
  });
  yearSel.addEventListener('change', () => { if (input.value.trim()) run(input.value.trim()); });
  // reflect the top-line total in the hero chip (its static fallback text otherwise drifts on rebuild)
  const heroCount = document.getElementById('docCountChip');
  if (heroCount) heroCount.textContent = topLineCount.toLocaleString() + ' documents';
})();

function passFilters(d) {
  if (activeTypes.size && !activeTypes.has(bucketOf(d))) return false;
  if (yearSel.value && String(d.fiscal_year) !== yearSel.value) return false;
  return true;
}

// ---------- report full-report formats ----------
// The two canonical "open the whole report" formats for a given annual report, looked up from the WHOLE
// corpus (whether or not they matched the query) — powers the "Full report" chooser. Slideshows / exec
// comparisons / spreadsheets are supplements, not the report itself, so they're excluded.
const isSupplement = s => /slide|comparison|spreadsheet|presentation|revenue estimate|forecast|\(summary\)/i.test(s);
function reportFormats(family, year) {
  const books = docs.filter(d => familyOf(d) === family && d.fiscal_year === year && d.scope === 'book');
  let linkedToc = null, singleFile = null;
  for (const b of books) {
    const s = (b.title + ' ' + b.url).toLowerCase();
    if (isSupplement(s)) continue;
    if (!linkedToc && /(with links|individual links|table of contents|apprpttoc|links\.pdf)/.test(s)) linkedToc = b;
    else if (!singleFile && (/single ?file/.test(s) || /approprpt/.test(s))) singleFile = b;
  }
  // approps "single file" is just titled "FY YYYY Appropriations Report" — fall back to the non-TOC book
  if (!singleFile) singleFile = books.find(b => { const s = (b.title + ' ' + b.url).toLowerCase(); return !isSupplement(s) && !/links|toc/.test(s); }) || null;
  return { linkedToc, singleFile };
}

// ---------- semantic loading (HTTP only) ----------
// Promise-cached + silent: the background warmup and a real search SHARE one load, so the model is
// never downloaded twice and a search arriving mid-warmup just awaits the same in-flight promise.
let semanticPromise = null;
function ensureSemantic() {
  if (isFile) return Promise.resolve(false);
  if (semanticReady) return Promise.resolve(true);
  if (semanticPromise) return semanticPromise;
  semanticPromise = (async () => {
    // dynamic import → ABSOLUTE url (a bare "assets/…" specifier is rejected as a module name)
    const tfUrl = new URL(ASSET + 'vendor/transformers/transformers.min.js', document.baseURI).href;
    const tf = await import(tfUrl);
    pipeline = tf.pipeline;
    const env = tf.env;
    env.allowRemoteModels = false;
    env.allowLocalModels = true;
    env.localModelPath = ASSET + 'models/';
    env.backends.onnx.wasm.wasmPaths = ASSET + 'vendor/transformers/';
    env.backends.onnx.wasm.numThreads = 1; // single-thread: no COOP/COEP needed
    vecIndex = await (await fetch(ASSET + 'index-vec.json?v=34')).json();
    extractor = await pipeline('feature-extraction', vecIndex.model);
    semanticReady = true;
    return true;
  })().catch(e => { semanticPromise = null; console.warn('Semantic search unavailable, using keyword fallback:', e); return false; });
  return semanticPromise;
}

function decodeVec(b64) {
  const bin = atob(b64), n = bin.length, f = new Float32Array(n);
  for (let i = 0; i < n; i++) { let v = bin.charCodeAt(i); if (v > 127) v -= 256; f[i] = v / 127; }
  return f;
}

function keywordScore(qWords, d) {
  if (!qWords.length) return 0;
  const hay = (d.title + ' ' + d.sub + ' ' + d.category + ' ' + d.doc_type + ' ' + (d.kw || '')).toLowerCase();
  const title = d.title.toLowerCase();
  let any = 0, inTitle = 0;
  for (const w of qWords) { if (hay.includes(w)) any++; if (title.includes(w)) inTitle++; }
  return (any / qWords.length) * 0.6 + (inTitle / qWords.length) * 0.4;
}

// ---------- typo tolerance ----------
// Levenshtein edit distance (small strings only — agency codes / name words).
function lev(a, b) {
  const m = a.length, n = b.length;
  const dp = Array.from({ length: m + 1 }, (_, i) => i);
  for (let j = 1; j <= n; j++) {
    let prev = dp[0]; dp[0] = j;
    for (let i = 1; i <= m; i++) {
      const tmp = dp[i];
      dp[i] = a[i - 1] === b[j - 1] ? prev : 1 + Math.min(prev, dp[i], dp[i - 1]);
      prev = tmp;
    }
  }
  return dp[m];
}
// A query word "matches" an agency token allowing small misspellings. Gated to tokens ≥5 chars (so a
// typo'd "ahccs"≈"ahcccs" / "correctons"≈"corrections" still picks the agency) while 3–4-char codes
// (asu, aph, adot) stay EXACT — fuzzing those would mis-fire on unrelated words. tol = 1 (≥5) / 2 (≥8).
function fuzzyEq(a, b) {
  if (a === b) return true;
  const L = Math.max(a.length, b.length);
  if (L < 5) return false;
  const tol = L >= 8 ? 2 : 1;
  if (Math.abs(a.length - b.length) > tol) return false;  // cheap prefilter: can't be within tol
  return lev(a, b) <= tol;
}
const anyFuzzy = (qWords, tokens) => qWords.some(w => tokens.some(t => fuzzyEq(w, t)));
// Words common to agency names AND to ordinary budget prose ("general appropriation act", "public
// schools"…). A match on one of these still clears the per-agency specificity penalty, but does NOT earn
// the decisive +0.25 name lift on its own — otherwise "general appropriation act provisions" mis-fires on
// "Attorney General". A DISTINCTIVE word (revenue, corrections, ahcccs, attorney…) still earns the lift.
const GENERIC_NAME_WORDS = new Set(['general', 'public', 'state', 'federal', 'service', 'services', 'affairs',
  'office', 'department', 'board', 'commission', 'authority', 'system', 'fund', 'special', 'county', 'arizona',
  'program', 'programs', 'committee', 'joint']);
const distinctiveFuzzy = (qWords, tokens) =>
  qWords.some(w => !GENERIC_NAME_WORDS.has(w) && tokens.some(t => fuzzyEq(w, t)));

// ---------- run a search ----------
async function run(query) {
  const qWords = [...new Set((query.toLowerCase().match(/[a-z0-9]{3,}/g) || []))];
  // Fiscal year(s) named in the query — accept the 4-digit "2026", the "fy26" / "fy 26" shorthand, AND a
  // bare two-digit "26". A standalone 2-digit token maps to a fiscal year only when it lands in a real
  // range (00–40 → 20xx, 80–99 → 19xx; the corpus spans FY1984–2027) — and even a wrong guess is
  // harmless: the +0.15 boost only lifts docs whose fiscal_year EQUALS it, so a non-year number lifts
  // nothing. `\b\d{2}\b` can't match inside a 4-digit year, so "2026" isn't double-read.
  const yearFrom2 = n => (n <= 40 ? 2000 + n : n >= 80 ? 1900 + n : null);
  const ql = query.toLowerCase();
  const qYears = [...new Set([
    ...[...ql.matchAll(/\b(?:fy\s?)?(20\d{2})\b/g)].map(m => Number(m[1])),          // 4-digit: 2026, fy2026
    ...[...ql.matchAll(/\bfy\s?(\d{2})\b/g)].map(m => 2000 + Number(m[1])),          // fy + 2-digit: fy26
    ...[...ql.matchAll(/\b(\d{2})\b/g)].map(m => yearFrom2(Number(m[1]))),           // bare 2-digit: 26
  ].filter(y => y != null))];
  // Family abbreviations users type: "ar"/"approps"/"appropriations report" → Appropriations Report;
  // "br"/"baseline book"/"baseline" → Baseline. ("ar"/"br" are 2 chars, so qWords (≥3) drops them — we
  // read the raw query here.) Used for a family score boost AND to enrich the embed text below so the
  // bare abbreviation still embeds toward the right report.
  const wantApprops = /\b(ar|approps?|appropriations?(\s+report)?|approp\s*rpt)\b/i.test(query);
  const wantBaseline = /\b(br|baselines?(\s+book)?)\b/i.test(query);
  // External-financials categories (5th feed): same family-synonym idea — when the query names one of the
  // new document families, boost that category (the docs aren't in a Baseline/Approps `familyOf`, so these
  // gate on `d.category`). AFR/exec-budget short forms also enrich the embed text so the bare term embeds
  // toward the right doc. The agency-submission boost can't flood results: a bare "budget request" still
  // hits the −0.45 agency-scope penalty unless the query also names the agency.
  const wantAFR = /\b(afr|acfr|annual (comprehensive )?financial report|comprehensive annual financial report|financial report|financial statements)\b/i.test(query);
  const wantExecBudget = /\b(executive budget|state agency detail|state funds|sources and uses)\b/i.test(query);
  const wantBudgetRequest = /\b(budget request|budget submission|agency submission|operating budget request)\b/i.test(query);
  // Specific publications whose distinctive word collides with an agency name (e.g. "tax handbook" vs the
  // "Tax Appeals" board). Boost the actual publication's doc_type/category so it isn't buried by the agency.
  const wantTaxHandbook = /\b(tax handbook|handbook)\b/i.test(query);
  let embedText = query;
  if (wantApprops && !/appropriation/i.test(query)) embedText += ' appropriations report';
  if (wantBaseline && !/baseline/i.test(query)) embedText += ' baseline book';
  if (wantAFR && !/annual financial/i.test(query)) embedText += ' annual financial report';
  if (wantExecBudget && !/executive budget/i.test(query)) embedText += ' executive budget';
  // Topic synonyms → agency identity. Plain-language topic words ("medicaid", "prison", "highway") don't
  // appear in an agency's acronym/name tokens, so without help they take the −0.45 agency-scope penalty and
  // sink below incidental matches. Injecting the agency's code into qWords (so the acro/agtok match fires)
  // + enriching the embed text makes "medicaid funding" lead with AHCCCS, "prison budget" with Corrections.
  // [match, token-injected-into-qWords (an agency code or distinctive name word that hits its acro/agtok),
  //  embed-text enrichment]. Keep the token to something that actually appears in the target agency's
  // acro/agtok — verified by relevance.test.mjs. Avoid bare words that collide across agencies.
  const TOPIC_SYNONYMS = [
    [/\bmedicaid\b/i, 'ahcccs', 'AHCCCS Medicaid health care cost containment'],
    [/\b(behavioral|mental)\s+health\b/i, 'ahcccs', 'AHCCCS behavioral health Medicaid'],
    [/\b(prison|prisons|inmate|inmates|incarcerat\w*)\b/i, 'corrections', 'Department of Corrections prisons'],
    [/\b(highway|highways|freeway|freeways|roads?|transit)\b/i, 'transportation', 'Department of Transportation highways roads'],
    [/\b(k-?12|schools?|classrooms?)\b/i, 'education', 'Department of Education K-12 public schools'],
    [/\b(foster|cps|child\s+welfare)\b/i, 'dcs', 'Department of Child Safety foster care'],
    [/\b(unemployment|snap|food\s+stamps|welfare)\b/i, 'des', 'Department of Economic Security unemployment'],
    [/\b(environment|environmental|pollution|air\s+quality)\b/i, 'environmental', 'Department of Environmental Quality pollution'],
    [/\b(water|drought|groundwater)\b/i, 'water', 'Department of Water Resources water'],
    [/\bveterans?\b/i, 'veterans', "Department of Veterans' Services veterans"],
    [/\b(national\s+guard|militia)\b/i, 'dema', 'Emergency and Military Affairs National Guard'],
    [/\b(wildlife|hunting|fishing)\b/i, 'game', 'Game and Fish Department wildlife'],
    [/\b(state\s+parks|\bparks)\b/i, 'parks', 'State Parks Board'],
    [/\b(wildfire|forestry|firefighting)\b/i, 'forestry', 'Forestry and Fire Management wildfire'],
  ];
  for (const [re, tok, phrase] of TOPIC_SYNONYMS) {
    if (re.test(query)) { if (tok && !qWords.includes(tok)) qWords.push(tok); embedText += ' ' + phrase; }
  }
  // feedback only if the model isn't warm yet (rare once the background preload has run)
  if (!semanticReady && !isFile) setStatus('Preparing search…');
  const semantic = await ensureSemantic();
  let q = null;
  if (semantic) { setStatus('Searching…'); q = (await extractor([embedText], { pooling: 'mean', normalize: true })).tolist()[0]; }

  let namedAgency = false;   // did the query name a specific agency (acronym or distinctive name word)?
  let ranked = docs.filter(passFilters).map(d => {
    const kw = keywordScore(qWords, d);
    let score = kw;
    if (semantic) {
      const v = decodeVec(vecIndex.vec[d.id]);
      let dot = 0; for (let i = 0; i < v.length; i++) dot += q[i] * v[i];
      score = 0.8 * dot + 0.2 * kw;
    }
    // decisive bonus when a query word matches this agency's code/acronym (asu, aph, ica…) — short
    // acronyms are weak in the embedding, so this makes "asu baseline" pick ASU outright. Typo-tolerant
    // for ≥5-char acronyms (so "ahccs"≈"ahcccs" still fires) via fuzzyEq; 3–4-char codes stay exact.
    const acroHit = d.acro ? anyFuzzy(qWords, d.acro.split(' ')) : false;
    if (acroHit) score += 0.35;
    // SCOPE: whole-report books should lead generic queries ("2027 baseline", "appropriations report"),
    // while a per-agency section only ranks high when the query actually names its agency.
    if (d.scope === 'book') {
      score += 0.12;
      // keep the main book above its own supplements (slideshow / exec comparison / TOC / summary)
      if (/\((Slideshow|Executive Comparison|Table of Contents|Summary)\)/.test(d.title)) score -= 0.07;
    } else if (d.scope === 'agency') {
      const at = (d.agtok || '').split(' ');
      const named = acroHit || anyFuzzy(qWords, at);   // did the query name THIS agency? (typo-tolerant for ≥5-char tokens)
      if (!named) score -= 0.45;                         // generic query -> sink below the book
      // a DISTINCTIVE name-word match (not the acronym, not a generic word) gets a positive lift too, so
      // a typo'd full name ("correctons baseline") still surfaces the agency — a typo zeroes the
      // keyword/semantic base, and penalty-removal alone leaves it flat against the books' "baseline" match.
      else if (!acroHit && distinctiveFuzzy(qWords, at)) score += 0.25;
    } else if (d.scope === 'summary') {
      // statewide summary section (general fund summary, appropriation act provisions, BSF…):
      // a real document-level page, so NO agency penalty. Small lift — above neutral but below the
      // whole book (+0.12), so "2027 baseline" still leads with the book while "general fund summary"
      // surfaces this section on its own distinctive title.
      score += 0.05;
    }
    // family synonyms: a query that says "ar" / "approps" / "appropriations report" boosts Appropriations
    // docs; "br" / "baseline (book)" boosts Baseline docs — so the abbreviations land on the right family.
    const fam = familyOf(d);
    if (wantApprops && fam === 'Appropriations Report') score += 0.15;
    if (wantBaseline && fam === 'Baseline') score += 0.15;
    // 5th-feed category boosts (parallel to the family synonyms above)
    if (wantAFR && d.category === 'Annual Financial Report') score += 0.15;
    if (wantExecBudget && d.category === 'Executive Budget') score += 0.15;
    if (wantBudgetRequest && d.category === 'Agency Budget Request') score += 0.15;
    if (wantTaxHandbook && (d.doc_type === 'Tax Handbook' || d.category === 'Tax Handbook')) score += 0.25;
    // explicit fiscal-year match: "2026 appropriations report" should prefer FY2026 docs
    if (d.fiscal_year && qYears.includes(d.fiscal_year)) score += 0.15;
    // recency: newest fiscal year first. With NO year named this is DECISIVE (0.03/yr) so e.g. "revenues"
    // reliably ranks the Dept of Revenue FY2026 report above FY2024 despite int8-quantization noise. When
    // a year IS named, stay gentle (0.003/yr) so it can't fight the explicit +0.15 year match.
    if (d.fiscal_year) {
      score += qYears.length
        ? Math.max(-0.06, (d.fiscal_year - 2027) * 0.003)
        : Math.max(-0.45, (d.fiscal_year - 2027) * 0.05);   // 0.05/yr beats int8-cosine noise even at a 1-yr gap
    }
    return { d, score };
  });
  ranked.sort((a, b) => b.score - a.score);
  // Show confident matches above the floor; if too few clear it, still show the best handful
  // (so a content query never dead-ends), then GROUP report sub-pages under their annual report.
  const floor = semantic ? 0.30 : 0.12;
  const strong = ranked.filter(r => r.score > floor);
  const base = strong.length >= 4 ? strong : ranked.slice(0, 12);

  // Group Baseline/Appropriations matches by annual report (family + fiscal year); other docs stand alone.
  // `base` is sorted high→low, so each group is created at its best member's score and `entries` stays in
  // best-first order; capping at 15 then limits the number of result CARDS (a report counts once).
  const entries = [];
  const groupByKey = new Map();
  for (const r of base) {
    const fam = familyOf(r.d);
    if (fam && r.d.fiscal_year) {
      const key = fam + '::' + r.d.fiscal_year;
      let g = groupByKey.get(key);
      if (!g) { g = { kind: 'group', family: fam, year: r.d.fiscal_year, members: [] }; groupByKey.set(key, g); entries.push(g); }
      g.members.push(r);
    } else {
      entries.push({ kind: 'doc', d: r.d, score: r.score });
    }
  }
  // Collapse an agency's repeated per-year report cards. For an agency-specific query the user wants the
  // LATEST baseline and LATEST appropriations for that agency (plus its budget submission) — not the same
  // agency listed once per fiscal year. `entries` is newest-first (recency), so keep the first group per
  // (agency, family) and drop older-year duplicates of the SAME agency. Book/summary-headlined groups
  // (generic queries like "baseline" / "appropriations report") have no agency identity, so they're never
  // collapsed and still list every year. (Headline logic mirrors groupCard so we key on the displayed head.)
  // Key the collapse on the agency NAME from the title (stable across years) — NOT the agency code, which
  // drifts year-to-year in the source index PDFs (e.g. Revenue is "rev" FY23–26 but "dor" FY27), which
  // would leak an extra older-year card. The name prefix ("Revenue, Department of") is consistent.
  const agencyName = d => d.title.split(/\s+[—–-]\s+FY\s*\d{4}/)[0].trim().toLowerCase();
  const seenAgencyFam = new Set();
  const seenDocTitle = new Set();   // drop a SECOND standalone doc with an identical title (true dup rows)
  const deduped = entries.filter(e => {
    if (e.kind === 'doc') {
      const t = e.d.title.toLowerCase();
      if (seenDocTitle.has(t)) return false;
      seenDocTitle.add(t); return true;
    }
    const agencySubs = e.members.filter(m => m.d.scope === 'agency');
    const head = (agencySubs.length && agencySubs[0].score >= e.members[0].score - 0.15) ? agencySubs[0] : e.members[0];
    if (head.d.scope !== 'agency') return true; // whole-book / summary headline → keep every year
    const key = agencyName(head.d) + '::' + e.family;
    if (seenAgencyFam.has(key)) return false;   // already showed this agency's latest year for this family
    seenAgencyFam.add(key); return true;
  });
  const cards = deduped.slice(0, 15);

  render(cards, qWords);
  const m = semantic ? 'Semantic search' : 'Keyword search';
  modeNote.textContent = semantic
    ? 'Semantic search — matched by meaning, running entirely in your browser.'
    : 'Keyword search (open over http:// for full semantic search).';
  setStatus(`${m} — ${cards.length} result${cards.length === 1 ? '' : 's'}` +
    (activeTypes.size || yearSel.value ? ' (filtered)' : ''));
}

// ---------- render ----------
const FILE_IC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 2h9l5 5v15H6z"/><path d="M14 2v6h6"/></svg>';
const CAL_IC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="3"/><path d="M16 2v4M8 2v4M3 10h18"/></svg>';
const OPEN_IC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
const BOOK_IC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h13a2 2 0 0 1 2 2v14H6a2 2 0 0 1-2-2z"/><path d="M4 18a2 2 0 0 1 2-2h13"/></svg>';
const CHEV_IC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg>';

function esc(s) { return s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
function highlight(s, qWords) {
  let t = esc(s);
  for (const w of qWords) t = t.replace(new RegExp('(' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<mark>$1</mark>');
  return t;
}

// one result row — also reused inside a group's "more results" tray
function docRow(d, score, qWords) {
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const meta = [d.category, d.doc_type, d.fiscal_year ? 'FY ' + d.fiscal_year : ''].filter(Boolean).join(' · ');
  const ic = /Meeting/.test(d.doc_type) ? CAL_IC : FILE_IC;
  return `<a class="doc" href="${d.url}" target="_blank" rel="noopener">
    <span class="doc-ic">${ic}</span>
    <span class="doc-main">
      <span class="doc-title">${highlight(d.title, qWords)}</span>
      <span class="doc-sub">${d.sub ? highlight(d.sub, qWords) + ' &middot; ' : ''}${esc(meta)}</span>
    </span>
    <span class="rel" title="relevance">${pct}%<span class="bar"><i style="width:${pct}%"></i></span></span>
    <span class="doc-pill">${OPEN_IC} Open</span>
  </a>`;
}

// a report group — a sub-page is the headline when one is competitive; a context strip offers the whole
// report (via the format-chooser modal) and the other matched sub-pages collapsed under "N more results".
// A generic "whole report" headline row — used when the best match for a Baseline/Appropriations group IS
// the report itself (a generic query like "baseline" / "2026 appropriations report"). It shows ONLY the
// report name + a single click that opens the format chooser. We deliberately NEVER render a format
// VARIANT ("Single File PDF" / "Version with Individual Links") or a SUPPLEMENT (slideshow / exec
// comparison) as its own result row — the chooser modal is the one path to the PDF. Reuses the `.grp-full`
// click delegation; href="#" + preventDefault keeps the `.doc` (anchor) styling.
function reportHeadlineRow(family, year, score, bothFormats) {
  const pct = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const sub = bothFormats ? 'Whole report &middot; choose Linked Table of Contents or Single File PDF' : 'Whole report';
  const pill = bothFormats ? 'Choose format' : 'Open report';
  // `grp-report` is a CLICK HOOK ONLY (no CSS) — must NOT reuse `grp-full`, whose solid-blue button styling
  // would paint the entire card blue. The `doc` class gives it the normal white result-card look.
  return `<a class="doc grp-report" href="#" data-family="${esc(family)}" data-year="${year}">
    <span class="doc-ic">${BOOK_IC}</span>
    <span class="doc-main">
      <span class="doc-title">FY ${year} ${esc(family)}</span>
      <span class="doc-sub">${sub}</span>
    </span>
    <span class="rel" title="relevance">${pct}%<span class="bar"><i style="width:${pct}%"></i></span></span>
    <span class="doc-pill">${BOOK_IC} ${pill}</span>
  </a>`;
}

function groupCard(g, qWords) {
  const best = g.members[0];
  // Promote a PER-AGENCY page to the headline even when the whole book scored higher — the named agency's
  // page is the more useful landing spot and the whole report stays one click away under "Full report".
  // Only per-agency pages are promoted (within 0.15 of the best member); a SUMMARY section headlines only
  // when it's genuinely the top match (so generic "2026 baseline" keeps the whole report as headline).
  const agencySubs = g.members.filter(m => m.d.scope === 'agency');
  const head = (agencySubs.length && agencySubs[0].score >= best.score - 0.15) ? agencySubs[0] : best;
  // siblings = other matched sub-pages. Book/format variants are NEVER listed as rows (modal only).
  const sibs = g.members.filter(m => m.d.scope !== 'book' && m !== head).slice(0, 8);
  const fmt = reportFormats(g.family, g.year);
  const hasFull = !!(fmt.linkedToc || fmt.singleFile);
  const moreBtn = sibs.length ? `<button class="grp-more" type="button">${sibs.length} more result${sibs.length === 1 ? '' : 's'} ${CHEV_IC}</button>` : '';
  const tray = sibs.length ? `<div class="tray">${sibs.map(m => docRow(m.d, m.score, qWords)).join('')}</div>` : '';

  // CASE A: the whole report itself is the best match (generic query). Render ONE generic report card that
  // opens the chooser — never a "(Single File)" / "(with Links)" / slideshow row.
  if (head.d.scope === 'book') {
    if (!hasFull) return docRow(head.d, head.score, qWords);     // only a supplement on file (rare archive year)
    const both = !!(fmt.linkedToc && fmt.singleFile);
    const card = reportHeadlineRow(g.family, g.year, head.score, both);
    if (!sibs.length) return card;
    return `<div class="grp">
      ${card}
      <div class="ctx"><div class="ctx-row">
        <span class="badge">${BOOK_IC} Matched sections in this report</span>
        <span class="spacer"></span>
        ${moreBtn}
      </div>${tray}</div>
    </div>`;
  }

  // CASE B: an agency / summary sub-page is the headline — show it; the whole report is behind "Full report".
  if (!hasFull && !sibs.length) return docRow(head.d, head.score, qWords);
  const badge = `Part of the FY ${g.year} ${g.family}`;
  const fullBtn = hasFull ? `<button class="grp-full" type="button" data-family="${esc(g.family)}" data-year="${g.year}">${BOOK_IC} Full report</button>` : '';
  return `<div class="grp">
    ${docRow(head.d, head.score, qWords)}
    <div class="ctx"><div class="ctx-row">
      <span class="badge">${BOOK_IC} ${esc(badge)}</span>
      <span class="spacer"></span>
      ${fullBtn}${moreBtn}
    </div>${tray}</div>
  </div>`;
}

function render(cards, qWords) {
  if (introCard) introCard.hidden = true;   // intro card removed from the page; guard if absent
  resultsCard.hidden = false;
  resultsCount.textContent = cards.length + ' found';
  if (!cards.length) { resultsEl.innerHTML = '<p class="empty">No documents matched. Try fewer or different words, or clear the filters.</p>'; return; }
  resultsEl.innerHTML = cards.map(e => e.kind === 'group' ? groupCard(e, qWords) : docRow(e.d, e.score, qWords)).join('');
}

// ---------- report chooser modal + group interactions ----------
const reportModal = $('#reportModal'), rmTitle = $('#rmTitle'), rmLinked = $('#rmLinked'), rmSingle = $('#rmSingle');
function openReport(family, year) {
  const { linkedToc, singleFile } = reportFormats(family, year);
  // only one format on file for this year → just open it; no point in a one-option chooser
  if (linkedToc && !singleFile) return window.open(linkedToc.url, '_blank', 'noopener');
  if (singleFile && !linkedToc) return window.open(singleFile.url, '_blank', 'noopener');
  if (!linkedToc && !singleFile) return;
  rmTitle.textContent = `FY ${year} ${family}`;
  rmLinked.href = linkedToc.url; rmSingle.href = singleFile.url;
  reportModal.classList.add('open');
}
function closeReport() { reportModal.classList.remove('open'); }
if (reportModal) {
  reportModal.addEventListener('click', e => { if (e.target === reportModal) closeReport(); });
  $('#rmClose').addEventListener('click', closeReport);
  rmLinked.addEventListener('click', closeReport);   // links still open in a new tab via target=_blank
  rmSingle.addEventListener('click', closeReport);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeReport(); });
}
// delegate group affordances (the rows are rebuilt via innerHTML on every search)
resultsEl.addEventListener('click', e => {
  const full = e.target.closest('.grp-full, .grp-report');   // "Full report" button OR a generic report card
  if (full) { e.preventDefault(); openReport(full.dataset.family, Number(full.dataset.year)); return; }
  const more = e.target.closest('.grp-more');
  if (more) { e.preventDefault(); more.classList.toggle('open'); const t = more.closest('.ctx').querySelector('.tray'); if (t) t.classList.toggle('open'); }
});

// ---------- wire up ----------
form.addEventListener('submit', e => { e.preventDefault(); const q = input.value.trim(); if (q) run(q); });
document.querySelectorAll('[data-example]').forEach(a =>
  a.addEventListener('click', e => { e.preventDefault(); input.value = a.dataset.example; run(a.dataset.example); }));
setStatus(isFile
  ? `${topLineCount.toLocaleString()} documents indexed · keyword search (open over http:// for semantic search)`
  : `${topLineCount.toLocaleString()} documents indexed · preparing instant search…`);

// ---------- background warmup ----------
// Download + init the model during the user's read/type time so the FIRST search is instant.
// Skip on metered / very-slow links (don't silently spend someone's cellular data) and on file://;
// those fall back to loading on first search-box focus.
const conn = navigator.connection || navigator.webkitConnection || null;
const metered = conn && (conn.saveData || /(^|\b)(slow-)?2g\b/.test(conn.effectiveType || ''));
function warmup() {
  ensureSemantic().then(ok => {
    // only touch the status if the user hasn't started searching yet
    if (input.value.trim() || !resultsCard.hidden) return;
    setStatus(ok
      ? `${topLineCount.toLocaleString()} documents · ready for instant semantic search`
      : `${topLineCount.toLocaleString()} documents indexed · type a question to search`);
  });
}
if (isFile) {
  setStatus(`${topLineCount.toLocaleString()} documents indexed · keyword search (open over http:// for semantic search)`);
} else if (metered) {
  setStatus(`${topLineCount.toLocaleString()} documents indexed · type a question to search`);
  input.addEventListener('focus', ensureSemantic, { once: true }); // load on demand instead of auto
} else {
  // defer to idle so the warmup never competes with the page becoming interactive
  (window.requestIdleCallback ? requestIdleCallback(warmup, { timeout: 2500 }) : setTimeout(warmup, 1200));
}

// ---------- deep link ----------
// The home page's hero search box is a GET <form action="subpage-search_jlbc.html"> with an
// input named "q". Arriving here as ?q=… (or via an example chip link) should fill the box and
// run the search immediately. run() awaits the model itself on HTTP (keyword-only on file://),
// so we just set the value and call it.
(function deepLinkSearch() {
  const q = (new URLSearchParams(location.search).get('q') || '').trim();
  if (!q) return;
  input.value = q;
  run(q);
})();
