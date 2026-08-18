"""Assemble a run directory into a reviewable HTML report bundle.

Turns eval/results/agent/<run>/ (raw transcripts + scores + judge) into
eval/results/agent/<run>/report/ (a self-contained, styled, navigable
HTML site):

    index.html              THE page: two main sections —
                            1) "Latest Run Metrics": top-line metric cards
                               for the MOST RECENT run across the whole tree
                               (so an older run's report still shows the
                               latest numbers).
                            2) "Per-Query": one row per query, each from that
                               query's MOST RECENT run, with a "last run"
                               date + run-id column (queries can last run at
                               different times). Plus the tool-error ledger.
    per-query/<id>.html     one styled page per query: regrouped metrics
                            (accuracy | cost | efficiency), judge review,
                            and the conversation from that query's latest run.
    historical.html         one page, two tabs:
                            Tab 1 — top-line metrics over time (every run,
                                    oldest -> newest; blank + note for metrics
                                    that run didn't collect).
                            Tab 2 — per-query timeline: each query's metrics
                                    across every run it appeared in.
    per-query/<id>.jsonl    raw transcript copy for the exact record
    raw/                    copies of scores.json, judge.json, manifest.json

WHY styled HTML instead of markdown: Destin wants a report that LAUNCHES
at the end of a run and that he can navigate in a browser — a table of
every metric, the conversation per query as the app would have shown it
(no streaming-delta stutter), and the judge's verdict, readable without
any tool.

"Latest run" semantics (measured against the actual run tree): runs live in
eval/results/agent/<ts>-<sha>/ with a manifest.json timestamp (the old runs
have one too, so dirname is only the fallback). Different queries can appear
in different runs (the 45-query quick set is not one atomic run), so each
query's "last run" can be a different run than the overall latest.

Historical gaps: some metrics (accurate_rate, figures, document_correctness)
only exist in the consolidated schema (2026-08-17+). Old runs lack them, so
the historical page shows a blank cell + a legend note ("not collected in
this run") rather than inventing a value. (Destin's call, 2026-08-17.)

Conversation reconstruction: the transcript records the assistant's
streamed deltas per turn. Some models re-emit growing prefixes, so the
READABLE message is the LAST delta of a phase (it holds the full
accumulated text); a tool call with no preceding deltas means the model
went straight to a tool. So per turn: if deltas exist, the last delta is
the assistant message; tool calls render as attempted tool calls in
between.

Usage:
    uv run python -m eval.report_bundle <run-dir>          # writes report/ + opens index.html
    uv run python -m eval.report_bundle <run-dir> --no-open

Free (no model calls) — reads the run dirs only.
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import sys
import webbrowser
from collections import Counter
from pathlib import Path

COLUMNS: list[tuple[str, str]] = [
    ("query_id", "query"), ("shape", "shape"), ("set", "set"), ("ok", "ok"),
    ("key_fact_rate", "fact rate"), ("accurate", "accurate"),
    ("steps", "turns"), ("retrieve_call_count", "retrieves"),
    ("retrieval_efficiency", "retr eff"), ("verified_citations", "cites ok"),
    ("cite_pass_rate", "cite pass"), ("first_try_cite_rate", "1st-try"),
    ("figure_coverage", "fig cov"), ("total_tokens", "tokens"),
    ("cost_usd", "cost"),
]

# New per-query columns added by this rework: last-run date + run-id.
EXTRA_COLUMNS: list[tuple[str, str]] = [
    ("last_run_date", "last run"), ("run_id", "run"),
]

SUMMARY_KEYS = [
    ("n", "queries"), ("errors", "crashed"), ("accurate_n", "accurate n"),
    ("accurate_rate", "accurate rate"), ("tokens_to_accurate_mean", "tokens/acc"),
    ("turns_to_accurate_mean", "turns/acc"), ("key_fact_rate_mean", "fact rate mean"),
    ("steps_mean", "turns mean"), ("retrieve_calls_mean", "retrieves mean"),
    ("retrieval_efficiency_mean", "retr eff mean"), ("cite_pass_rate", "cite pass"),
    ("total_cost_usd", "total cost"), ("cost_mean_usd", "cost/query"),
]

JUDGE_KEYS = ["holistic", "chunk_relevance", "claim_coverage_precision",
              "claim_coverage_recall", "figure_coverage_ok", "placement_ok"]

# Hoverable descriptions of each metric, in the analyst's context.
STAT_HELP = {
    "queries": "Number of queries in this run.",
    "crashed": "Queries whose terminal frame was not _done (crash). 0 is good.",
    "accurate n": "Queries that passed ALL key facts AND produced ≥1 verified citation — the headline bar.",
    "accurate rate": "Share of queries meeting the accurate bar. This is the headline quality number.",
    "tokens/acc": "Average tokens (input+output+cached) spent per ACCURATE query. Lower is better.",
    "turns/acc": "Average agent turns (assistant steps) per ACCURATE query. Lower is better.",
    "fact rate mean": "Mean fraction of the query's pinned key facts that appear in the final answer.",
    "turns mean": "Average agent turns across all queries.",
    "retrieves mean": "Average number of retrieve tool calls per query.",
    "retr eff mean": "Chunks actually used (cited or fact-bearing) ÷ chunks retrieved. 1.0 = no wasted retrieves.",
    "cite pass": "Passing citation attempts ÷ all attempts (retries included).",
    "total cost": "Total spend on the live agent run (model calls).",
    "cost/query": "Total cost ÷ number of queries.",
    "holistic_mean": "Judge's 1–5 overall answer quality (1 worst, 5 best).",
    "chunk_relevance_mean": "Judge-scored relevance of the retrieved chunks to the question (0–1).",
    "claim_coverage_precision_mean": "Of the judge's load-bearing claims, how many the answer actually covers (0–1).",
    "claim_coverage_recall_mean": "Of the answer's claims, how many were verified against cited chunks (0–1).",
    "fact rate": "Share of the query's pinned key facts present in the final answer. 1.0 = all.",
    "accurate": "Met the headline bar: all key facts + ≥1 verified citation.",
    "turns": "Agent steps taken to answer this query.",
    "retrieves": "Retrieve tool calls issued for this query.",
    "retr eff": "Used chunks ÷ retrieved chunks. 1.0 = every retrieved chunk was used.",
    "cites ok": "Verified citations in the final answer.",
    "cite pass": "Passing citation attempts ÷ all attempts.",
    "1st-try": "Share of citations that passed on the FIRST attempt (no retry).",
    "fig cov": "Share of the answer's figures that were linked to a verified citation.",
    "tokens": "Total tokens (input+output+cached) spent on this query.",
    "cost": "Model spend for this query.",
    "last run": "The date of the most recent run this query appeared in (queries in different sets can last run at different times).",
    "run": "The run id of that most recent run.",
}

CSS = """
:root { --bg:#f6f8fb; --card:#fff; --ink:#161b26; --muted:#5c6775;
        --accent:#2563eb; --ok:#0e9f5b; --warn:#d97706; --bad:#dc2626;
        --line:#e5eaf1; --tool:#f1f5f9; --tool-edge:#93c5fd;
        --user-bubble:#eaf1ff; --assistant-bubble:#fff; --chip:#eef1f6;
        /* app design tokens, ported from webapp/src/styles/tokens.css so the
           transcript renders with the app's own palette */
        --navy:#2b2f63; --navy-700:#232752; --navy-900:#181b3d; --navy-100:#e7e8f2;
        --az-gold:#1b6fc4; --az-gold-d:#145aa6; --az-gold-100:#dceaf7;
        --ink-2:#4a4e6a; --ink-3:#757895; --r-md:16px; --r-sm:12px; --r-pill:999px;
        --chat-danger:#c0392b; --chat-danger-tint:#fdecea; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; font:15px/1.6 -apple-system,"Segoe UI",Roboto,sans-serif;
       background:var(--bg); color:var(--ink); overflow-x:hidden; }
header { background:linear-gradient(120deg,#17233c 0%,#1d4ed8 60%,#2563eb 100%);
         color:#fff; padding:28px 44px; box-shadow:0 2px 12px rgba(20,30,60,.25); }
header h1 { margin:0; font-size:23px; font-weight:700; letter-spacing:.2px; }
header .sub { opacity:.9; margin-top:5px; font-size:13px; }
.wrap { max-width:1280px; margin:0 auto; padding:28px 44px 60px; }
h2 { margin-top:40px; font-size:20px; font-weight:700; color:#0f244f;
     border-bottom:2px solid var(--line); padding-bottom:8px; }
h2 .count { color:var(--muted); font-weight:500; font-size:14px; margin-left:8px; }
h3 { font-size:16px; font-weight:600; margin:22px 0 10px; color:#17305f; }
table { border-collapse:separate; border-spacing:0; width:100%; margin:14px 0;
        background:var(--card); box-shadow:0 1px 4px rgba(20,30,60,.08);
        border-radius:10px; overflow:hidden; }
/* A table must not stretch the page: .table-scroll clips wide tables so the
   page itself never scrolls horizontally; the table scrolls inside its own
   block. whole-page horizontal scroll is disabled on body. */
.table-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; margin:14px 0; }
.table-scroll table { margin:0; }
.table-scroll th { position:sticky; top:0; }
th,td { padding:9px 12px; text-align:left; border-bottom:1px solid var(--line);
        font-size:13.5px; white-space:nowrap; }
th { background:#eef2f9; font-weight:700; color:#23334f; cursor:pointer;
     user-select:none; position:sticky; top:0; z-index:1; }
th:hover { background:#e2e9f5; }
th .sort { font-size:10px; color:var(--muted); margin-left:4px; }
tr:last-child td { border-bottom:none; }
tbody tr:hover td { background:#f6f9ff; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
.good { color:var(--ok); font-weight:700; }
.warn { color:var(--warn); font-weight:700; }
.bad { color:var(--bad); font-weight:700; }
.muted { color:var(--muted); }
.badge { display:inline-block; font-size:12px; font-weight:700; border-radius:20px;
         padding:2px 10px; }
.badge.good { background:#e6f6ee; color:var(--ok); }
.badge.warn { background:#fdf1e0; color:var(--warn); }
.badge.bad { background:#fdeaea; color:var(--bad); }
.metric-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(158px,1fr));
               gap:12px; margin:16px 0; }
.metric { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:12px 16px; box-shadow:0 1px 3px rgba(20,30,60,.05); }
.metric .k { font-size:11px; text-transform:uppercase; letter-spacing:.05em;
             color:var(--muted); font-weight:600; }
.metric .v { font-size:19px; font-weight:700; margin-top:3px; font-variant-numeric:tabular-nums; }
.metric .v.good { color:var(--ok); } .metric .v.warn { color:var(--warn); }
.metric .v.bad { color:var(--bad); }
/* consolidated metric grid: labeled groups, so the per-query page reads in
   three scannable bands instead of one undifferentiated wall of cards. */
.metric-group { margin:14px 0 6px; }
.metric-group h3 { margin:0 0 8px; font-size:13px; text-transform:uppercase;
                   letter-spacing:.05em; color:var(--muted); }
.chat { border:1px solid var(--line); border-radius:12px; overflow:hidden;
        box-shadow:0 1px 4px rgba(20,30,60,.06); margin:16px 0; }
.msg { padding:14px 20px; }
.msg.user { background:var(--user-bubble); }
.msg.assistant { background:var(--assistant-bubble); border-top:1px solid var(--line); }
.msg .who { font-size:11px; font-weight:800; text-transform:uppercase;
            letter-spacing:.06em; color:var(--muted); margin-bottom:5px; }
.msg .body { white-space:pre-wrap; }
/* client-side markdown rendering of message bodies */
.msg .body p { margin:0 0 8px; }
.msg .body p:last-child { margin-bottom:0; }
.msg .body table { font-size:12.5px; margin:6px 0; }
.msg .body code { background:var(--chip); padding:1px 5px; border-radius:4px;
                  font-size:12.5px; font-family:ui-monospace,Menlo,monospace; }
.msg .body pre { background:#0f1b2e; color:#d9e3f5; padding:10px 14px; border-radius:8px;
                 overflow:auto; }
.msg .body pre code { background:none; color:inherit; padding:0; }
.msg .body blockquote { margin:6px 0; padding:4px 12px; border-left:3px solid var(--accent);
                        color:var(--muted); }
.msg .body h1,.msg .body h2 { font-size:15px; margin:10px 0 6px; color:#17305f; }
.msg .body ul,.msg .body ol { margin:6px 0; padding-left:22px; }
.tool { background:var(--tool); border-left:4px solid var(--tool-edge); padding:10px 16px;
        margin:10px 16px; border-radius:8px; font-size:13px; box-shadow:0 1px 2px rgba(20,30,60,.05); }
.tool .tname { font-weight:800; font-size:12.5px; text-transform:uppercase;
               letter-spacing:.04em; color:#1d4ed8; }
.tool .tinput { margin-top:6px; font-family:ui-monospace,Menlo,monospace; font-size:12.5px;
                white-space:pre-wrap; color:#2b3a57; background:#fff; padding:8px 10px;
                border-radius:6px; border:1px solid var(--line); }
.tool .tresult { margin-top:6px; color:var(--muted); font-size:12.5px; white-space:pre-wrap;
                 font-family:ui-monospace,Menlo,monospace; background:#fbfcfe; padding:8px 10px;
                 border-radius:6px; }
.back { display:inline-block; margin:0 0 14px; color:var(--accent); text-decoration:none;
        font-weight:700; font-size:14px; }
.back:hover { text-decoration:underline; }
.err { color:var(--bad); }
.claims { list-style:none; padding:0; margin:8px 0; }
.claims li { margin:5px 0; padding:6px 10px; background:var(--card);
             border:1px solid var(--line); border-radius:8px; font-size:13.5px; }
.claims .ok { color:var(--ok); font-weight:800; }
.claims .bad { color:var(--bad); font-weight:800; }
a { color:var(--accent); }

/* ---- nav bar across pages ---- */
.nav { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:22px; }
.nav a { display:inline-block; padding:7px 14px; border-radius:999px;
         font-size:13px; font-weight:700; color:var(--ink-2);
         background:var(--card); border:1px solid var(--line);
         text-decoration:none; }
.nav a:hover { background:#eef2f9; }
.nav a.active { background:var(--navy); color:#fff; border-color:var(--navy); }

/* ---- tabs (historical page) ---- */
.tabs { display:flex; gap:4px; margin:0 0 18px; border-bottom:2px solid var(--line); }
.tabs a { display:inline-block; padding:9px 18px; font-size:14px; font-weight:700;
          color:var(--muted); text-decoration:none; border-bottom:3px solid transparent;
          margin-bottom:-2px; }
.tabs a.active { color:var(--navy); border-bottom-color:var(--navy); }
.tabs a:hover { color:var(--accent); }

/* ---- tooltips (hoverable stat descriptions + query previews) ----
   A JS-driven tooltip (see below) renders the tip in a FIXED element
   appended to <body>, so it is NOT clipped by .table-scroll's overflow
   or any other container. The [data-tip] hint underline stays in CSS. */
[data-tip] { cursor:help; border-bottom:1px dotted var(--muted); }
#evtip { position:fixed; z-index:10000; max-width:min(340px, 90vw);
         background:#101a2c; color:#e7edf8; padding:8px 12px; border-radius:8px;
         font-size:12.5px; font-weight:400; line-height:1.45; white-space:normal;
         box-shadow:0 4px 14px rgba(10,18,35,.35); text-align:left;
         pointer-events:none; display:none; }
/* ---- app chat transcript (ported from webapp/src/styles/app.css) ----
   The eval transcript renders with the LIVE app's own classes + tokens so
   it looks like the real conversation, not a bespoke viewer. */
.chat-turn { display:flex; flex-direction:column; gap:8px; margin:18px 0; }
.chat-bubble { position:relative; background:var(--card); border:1px solid var(--line);
               border-radius:var(--r-md); padding:10px 16px; color:var(--ink);
               font-size:14px; max-width:65ch; }
.chat-bubble.has-tail { border-bottom-left-radius:4px; }
.chat-user-row { display:flex; justify-content:flex-end; }
.chat-user-bubble { background:var(--navy); color:#fff; border-radius:var(--r-md);
                    border-bottom-right-radius:4px; padding:10px 16px; max-width:78%;
                    font-size:14px; line-height:1.6; white-space:pre-wrap; }
.chat-stop-note { font-size:12px; color:var(--ink-3); font-style:italic; padding:0 4px; }
/* tool card + group, the app's own geometry */
.chat-tool { border-radius:var(--r-sm); border:1px solid var(--line);
             background:var(--card); max-width:65ch; overflow:hidden; margin:8px 0; }
.chat-tool.is-failed { border-color:var(--chat-danger); }
.chat-tool.is-inset { background:var(--canvas, #f5f5fa); }
.chat-tool-head { width:100%; display:flex; align-items:center; gap:8px; padding:6px 12px;
                  font-size:12.5px; color:var(--ink-2); }
.chat-tool-glyph { flex-shrink:0; color:var(--ink-3); }
.chat-tool.is-failed .chat-tool-glyph, .chat-tool.is-failed .chat-tool-label { color:var(--chat-danger); }
.chat-tool-label { font-weight:700; color:var(--ink-2); flex-shrink:0; }
.chat-tool-summary { color:var(--ink-3); font-size:12px; min-width:0; flex:1 1 auto;
                     overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chat-tool-summary::before { content:"↳ "; }
.chat-tool-body { border-top:1px solid var(--line); padding:8px 12px;
                  font-size:13px; color:var(--ink); }
.chat-tool-body pre { margin:4px 0; white-space:pre-wrap; font-size:12px;
                      font-family:ui-monospace,Menlo,monospace; color:var(--ink-2); }
.chat-tool-body .chip-row { display:flex; flex-wrap:wrap; gap:6px; }
.chat-chip { display:inline-flex; align-items:center; gap:4px; padding:1px 8px;
             font-size:11px; font-weight:700; border-radius:var(--r-pill);
             border:1px solid var(--line); background:var(--navy-100); color:var(--ink-2); }
.chat-chip.is-good { background:var(--az-gold-100); color:var(--az-gold-d); border-color:var(--az-gold); }
.chat-chip.is-bad { background:var(--chat-danger-tint); color:var(--chat-danger); border-color:var(--chat-danger); }
/* citation pills, the app's cite state language */
.chat-cite-pill { display:inline-flex; align-items:center; gap:4px; padding:1px 6px;
                  font-size:10px; font-weight:700; border-radius:4px; border:1px solid;
                  font-family:var(--font); cursor:pointer; }
.chat-cite-pill.is-verbatim { background:var(--az-gold-100); color:var(--az-gold-d); border-color:var(--az-gold); }
.chat-cite-pill.is-paraphrase { background:var(--navy-100); color:var(--ink-2); border-color:var(--line); }
.chat-cite-pill.is-failed { background:var(--chat-danger-tint); color:var(--chat-danger); border-color:var(--chat-danger); }
/* tool calls, app-like */
.tool { display:flex; align-items:flex-start; gap:8px; background:var(--tool);
        border:1px solid var(--line); border-left:4px solid var(--accent);
        padding:7px 12px; margin:8px 0; border-radius:8px; font-size:13px; }
.tool .tname { font-weight:800; font-size:12px; text-transform:uppercase;
               letter-spacing:.05em; color:#1d4ed8; white-space:nowrap; flex:none; }
.tool .tdetail { color:#2b3a57; overflow-wrap:anywhere; }
.tool .targs { color:var(--muted); font-family:ui-monospace,Menlo,monospace;
               font-size:12px; white-space:nowrap; }
.tool.retrieve { border-left-color:#2563eb; }
.tool.cite { border-left-color:#0e9f5b; }
.tool.result { border-left-color:#93c5fd; background:#f6f9ff; margin:2px 0 10px 28px;
               border-left-style:dashed; }
.tool.result.error { border-left-color:var(--bad); }
/* header + summary prettier */
header .runid { font-family:ui-monospace,Menlo,monospace; font-size:12px;
                opacity:.85; margin-top:8px; }
.summary-card { background:linear-gradient(180deg,#fff,#f7fafd); border:1px solid var(--line);
                border-radius:14px; padding:18px 22px; margin-top:18px;
                box-shadow:0 2px 10px rgba(20,30,60,.06); }
.summary-card h2 { margin-top:0; border:none; padding-bottom:0; font-size:17px; }
.hint { color:var(--muted); font-size:12.5px; margin:2px 0 0; }
.query-chip { display:inline-block; max-width:240px; overflow:hidden; text-overflow:ellipsis;
              white-space:nowrap; vertical-align:middle; }
/* The JS tooltip above handles rendering; the wrapper only needs to not
   clip the query-chip's ellipsis. */
.tooltip-wrap { display:inline-block; }
"""

JS = """
// Client-side markdown renderer for message bodies (limited, safe subset:
// the content is model prose with tables/bold/lists/code — we render those
// and escape everything else). No server dependency keeps the bundle a
// single static folder.
function md(text) {
  text = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  // fenced code
  text = text.replace(/```([\\s\\S]*?)```/g, "<pre><code>$1</code></pre>");
  // headings h2/h3 and bold
  text = text.replace(/^####[ \\t]*(.+)$/gm, "<h2>$1</h2>");
  text = text.replace(/^###[ \\t]*(.+)$/gm, "<h3>$1</h3>");
  text = text.replace(/\\*\\*(.+?)\\*\\*/g, "<strong>$1</strong>");
  text = text.replace(/\\*(.+?)\\*/g, "<em>$1</em>");
  text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
  // tables: line groups starting with | -> render <table>
  var lines = text.split("\\n"), html = [], i = 0, inT = false;
  while (i < lines.length) {
    var l = lines[i];
    if (l.trim().startsWith("|") && i + 1 < lines.length && lines[i+1].trim().startsWith("|")) {
      if (!inT) { html.push("<table>"); inT = true; }
      var cells = l.trim().split("|").slice(1, -1).map(function(c){ return c.trim(); });
      var tag = (i === 0 || /^\\s*:?-+:?\\s*$/.test(l.trim().replace(/[^|:|\\-\\s]/g, ""))) ? "th" : "td";
      // detect the header separator row (----) and skip rendering it as data
      if (inT && /^[\\s:|\\-]+$/.test(l.trim())) { i++; continue; }
      html.push("<tr><" + tag + ">" + cells.join("</" + tag + "><" + tag + ">") + "</" + tag + "></tr>");
    } else {
      if (inT) { html.push("</table>"); inT = false; }
      if (l.trim() !== "") html.push("<p>" + l + "</p>");
    }
    i++;
  }
  if (inT) html.push("</table>");
  // join and wrap
  return html.join("");
}
document.addEventListener("DOMContentLoaded", function () {
  // render message bodies
  document.querySelectorAll(".chat-bubble").forEach(function (b) {
    b.innerHTML = md(b.textContent);
  });
  // historical page tabs: show the tab named by ?tab= (default topline)
  function showTab(name) {
    document.querySelectorAll(".tabs a").forEach(function (a) {
      var on = a.getAttribute("data-tab") === name;
      a.classList.toggle("active", on);
    });
    document.querySelectorAll("[id^='tab-']").forEach(function (d) {
      d.style.display = d.id === "tab-" + name ? "" : "none";
    });
  }
  document.querySelectorAll(".tabs a").forEach(function (a) {
    a.addEventListener("click", function (e) {
      var name = a.getAttribute("data-tab");
      showTab(name);
      history.replaceState(null, "", "historical.html?tab=" + name);
      e.preventDefault();
    });
  });
  var m = location.search.match(/[?&]tab=([^&]+)/);
  if (m) showTab(m[1]);
  // ---- JS tooltip: renders [data-tip] in a FIXED element on <body> so the
  // tip is never clipped by .table-scroll or any other overflow container.
  var tip = document.createElement("div");
  tip.id = "evtip";
  document.body.appendChild(tip);
  function tipShow(el) {
    tip.textContent = el.getAttribute("data-tip");
    tip.style.display = "block";
    tipPos(el);
  }
  function tipPos(el) {
    var r = el.getBoundingClientRect();
    var tw = tip.offsetWidth, th = tip.offsetHeight;
    var x = r.left + r.width / 2 - tw / 2;
    // clamp horizontally so the tip never goes off the right/left viewport edge
    x = Math.max(8, Math.min(x, window.innerWidth - tw - 8));
    var y = r.top - th - 10;            // above the element
    var flip = y < 8;                    // not enough room above -> below
    if (flip) y = r.bottom + 10;
    if (y + th > window.innerHeight - 8) y = window.innerHeight - th - 8;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
    tip.style.transform = flip ? "translateY(-4px)" : "translateY(4px)";
  }
  document.querySelectorAll("[data-tip]").forEach(function (el) {
    el.addEventListener("mouseenter", function () { tipShow(el); });
    el.addEventListener("mousemove", function (e) {
      // follow horizontally only; vertical clamp stays anchored to the element
      var r = el.getBoundingClientRect(), tw = tip.offsetWidth;
      var x = Math.max(8, Math.min(e.clientX - tw / 2, window.innerWidth - tw - 8));
      tip.style.left = x + "px";
    });
    el.addEventListener("mouseleave", function () {
      tip.style.display = "none";
    });
  });
  // sortable tables: click a header to sort asc/desc
  document.querySelectorAll("table.sortable th").forEach(function (th, idx) {
    th.addEventListener("click", function () {
      var t = th.closest("table"), tbody = t.querySelector("tbody"), rows = Array.from(tbody.rows);
      var dir = t.getAttribute("data-dir") === "asc" ? "desc" : "asc";
      t.setAttribute("data-dir", dir);
      rows.sort(function (a, b) {
        var av = a.cells[idx].textContent.trim(), bv = b.cells[idx].textContent.trim();
        var an = parseFloat(av.replace(/[$,\\s]/g, "")), bn = parseFloat(bv.replace(/[$,\\s]/g, ""));
        var cmp = !isNaN(an) && !isNaN(bn) ? an - bn : av.localeCompare(bv);
        return dir === "asc" ? cmp : -cmp;
      });
      rows.forEach(function (r) { tbody.appendChild(r); });
      th.querySelector(".sort").textContent = dir === "asc" ? "▲" : "▼";
    });
  });
});
"""


def esc(v) -> str:
    return html.escape(str(v))


def _fmt(v, digits=4) -> str:
    """Format a metric value for display.

    WHY padding large floats with thousands separators instead of {:.4g}
    scientific notation: tokens/cost figures are read at a glance and
    '1.915e+05' is hard to compare to '191,480'. Keeps small floats intact.
    """
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    if isinstance(v, float):
        # {:.{digits}g} switches to scientific notation for values >= 10**digits
        # (e.g. 1e+04 at digits=4), which reads badly for token/cost figures. Any
        # value >= 1000 gets thousands separators instead; ratios < 1000 keep g.
        if abs(v) >= 1000:
            return f"{v:,.0f}" if v == int(v) else f"{v:,.2f}"
        return f"{v:.{digits}g}"
    if isinstance(v, int) and abs(v) >= 1000:
        return f"{v:,}"
    return str(v)


# Which metrics are "higher (≤1 scale) is better" for color coding.
HIGHER_BETTER = {
    "key_fact_rate", "accurate_rate", "cite_pass_rate", "first_try_cite_rate",
    "retrieval_efficiency", "figure_coverage", "chunk_relevance",
    "claim_coverage_precision", "claim_coverage_recall", "holistic",
    "document_correctness",
}
# Color a metric value: green for good, red for bad, amber for middling.
def _metric_class(key: str, v) -> str:
    if v is None or isinstance(v, bool):
        return ""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if key in HIGHER_BETTER:
        if x >= 0.9: return "good"
        if x >= 0.7: return "warn"
        return "bad"
    # lower is better (turns, retrieves, cost, tokens) — only tint extremes
    if key in ("cost_usd", "total_cost_usd", "cost_mean_usd"):
        return "good" if x < 0.02 else ("warn" if x < 0.05 else "bad")
    return ""


def _metric_value_class(key: str, v) -> str:
    """Safe value-class for the metric .v element.

    WHY this exists: the original code did cls = f" class='{cls}'" and then
    embedded it into class='v{cls}', producing malformed HTML like
    <div class='v class='warn''> — the browser parsed class 'v class=' and
    dropped the whole color. The class name must be joined into the attribute
    value, never pre-wrapped."""
    cls = _metric_class(key, v)
    return f" class='v {cls}'" if cls else " class='v'"


# ---------- run discovery / latest-run ----------

def _run_timestamp(run_dir: Path) -> str:
    """Sorted-key timestamp for a run dir: uses manifest.timestamp when present,
    else the dirname (both are 'YYYY-MM-DDTHHMMZ'). Historical pages sort runs by
    this. Fallback to dirname keeps pre-manifest runs usable."""
    mf = run_dir / "manifest.json"
    if mf.exists():
        try:
            ts = json.loads(mf.read_text(encoding="utf-8")).get("timestamp")
            if ts:
                return ts
        except (json.JSONDecodeError, OSError):
            pass
    return run_dir.name.split("-")[0] if "-" in run_dir.name else run_dir.name


def _load_run(run_dir: Path) -> dict:
    """Load one run's scores.json + optional judge.json/errors.json/manifest.json."""
    run_id = run_dir.name
    scores = {}
    if (run_dir / "scores.json").exists():
        scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    judge = {}
    if (run_dir / "judge.json").exists():
        judge = json.loads((run_dir / "judge.json").read_text(encoding="utf-8"))
    errors = []
    if (run_dir / "errors.json").exists():
        errors = json.loads((run_dir / "errors.json").read_text(encoding="utf-8"))
    manifest = {}
    if (run_dir / "manifest.json").exists():
        try:
            manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    return {"run_id": run_id, "dir": run_dir, "scores": scores,
            "judge": judge, "errors": errors, "manifest": manifest,
            "timestamp": _run_timestamp(run_dir)}


def _discover_runs(results_root: Path) -> list[dict]:
    """All run dirs under results_root/agent, oldest -> newest by timestamp.

    A 'run' is any directory holding a scores.json (the report bundle lives
    one level deeper, under <run>/report/, so it is not mistaken for a run)."""
    root = results_root / "agent"
    if not root.is_dir():
        return []
    runs = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if (child / "scores.json").exists():
            runs.append(_load_run(child))
    return sorted(runs, key=lambda r: r["timestamp"])


def _per_query_lookup(scores: dict) -> dict[str, dict]:
    """index per_query entries by query_id for a single run's scores."""
    return {r["query_id"]: r for r in scores.get("per_query", [])}


def _query_latest_runs(runs: list[dict]) -> dict[str, dict]:
    """Map query_id -> its MOST RECENT run dict (by run timestamp). Different
    queries can be present in different runs, so each query's 'last run' may be
    a different run than the index's overall latest run."""
    best: dict[str, dict] = {}
    for run in runs:  # runs are sorted oldest -> newest, so last wins
        for qid in _per_query_lookup(run["scores"]):
            best[qid] = run
    return best


def _latest_run(runs: list[dict]) -> dict | None:
    """The single most recent run across all runs."""
    return runs[-1] if runs else None


def _fmt_date(ts: str) -> str:
    """'2026-08-17T2324Z' -> '2026-08-17' (human date for the last-run column)."""
    return ts[:10] if len(ts) >= 10 else ts


def _load_all(results_root: Path) -> dict:
    """Load every run under results_root/agent for the multi-run pages."""
    return {"runs": _discover_runs(results_root)}


# ---------- conversation reconstruction ----------

_QUERY_TEXT_CACHE: dict[str, dict[str, str]] = {}


def _query_texts() -> dict[str, str]:
    """query_id -> question text, from eval/agent_queries.yaml.

    WHY the YAML instead of the transcript: the raw transcripts (*-r1.jsonl)
    are GITIGNORED (full chunk text), so a fresh checkout often has no
    transcript to read the user's question from — which is exactly why the
    hover previews stopped working. agent_queries.yaml is committed and
    always present. The transcript remains a fallback for queries not in the
    YAML (e.g. old ids before the query set existed)."""
    if _QUERY_TEXT_CACHE:
        return _QUERY_TEXT_CACHE["by_id"]
    out: dict[str, str] = {}
    root = Path(__file__).resolve().parent.parent
    path = root / "eval" / "agent_queries.yaml"
    if path.exists():
        try:
            import yaml
            for q in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
                qid = q.get("id")
                if qid and q.get("question"):
                    out[qid] = str(q["question"]).strip()
        except Exception:
            pass  # fall through to transcript-only mode
    _QUERY_TEXT_CACHE["by_id"] = out
    return out


def _user_message(run_dir: Path, qid: str) -> str:
    """The user's question for a query — drives hover previews.

    Prefers the committed query set (agent_queries.yaml), falls back to the
    first user_message event in the transcript (gitignored, may be absent)."""
    qtext = _query_texts().get(qid)
    if qtext:
        return qtext
    for e in _conversation_events(run_dir, qid):
        if e.get("type") == "user_message":
            return (e.get("text") or "").strip()
    return ""


def _conversation_events(run_dir: Path, qid: str) -> list[dict]:
    """Return the event stream as a list of dicts (type + payload)."""
    path = run_dir / f"{qid}-r1.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "event":
            out.append(rec["event"])
    return out


def render_chat_html(run_dir: Path, qid: str) -> str:
    """Render the conversation as it appeared in the app.

    Uses the LIVE app's own class structure (ported into CSS above):
    .chat-turn groups one user row + assistant bubble + tool cards;
    .chat-user-row/.chat-user-bubble for the question; .chat-bubble for
    assistant prose; .chat-tool cards for tool calls; .chat-cite-pill for
    citation attempts. This is the same markup the app renders, so the
    eval transcript looks like the real conversation.

    Reconstruction rule (verified against real transcripts): the assistant
    emits streamed deltas; some models re-emit growing prefixes, so the
    readable message is the LAST delta of a phase (it holds the full
    accumulated text). A tool call with NO preceding deltas means the model
    went straight to the tool.
    """
    evs = _conversation_events(run_dir, qid)
    if not evs:
        return "<p class='muted'>no transcript</p>"
    parts: list[str] = []  # each entry is one .chat-turn
    cur_deltas: list[str] = []
    thinking = ""

    def flush_turn():
        """Close the current turn: assistant bubble from the last delta +
        thinking; reset accumulators."""
        nonlocal cur_deltas, thinking
        inner = []
        if thinking:
            inner.append(f"<div class='chat-bubble'><div class='chat-stop-note'>"
                         f"reasoning: {esc(thinking[:200])}</div></div>")
            thinking = ""
        if cur_deltas:
            text = cur_deltas[-1].strip()  # last delta = full accumulated message
            cur_deltas = []
            if text:
                inner.append(f"<div class='chat-bubble has-tail'>{esc(text)}</div>")
        if inner:
            parts.append("<div class='chat-turn'>" + "".join(inner) + "</div>")

    for e in evs:
        t = e.get("type")
        if t == "user_message":
            flush_turn()
            parts.append(f"<div class='chat-turn'><div class='chat-user-row'>"
                         f"<div class='chat-user-bubble'>{esc(e.get('text',''))}</div>"
                         f"</div></div>")
        elif t == "assistant_thinking":
            thinking = (thinking + "\n" + (e.get("text") or "")).strip()
        elif t == "assistant_text_delta":
            cur_deltas.append(e.get("text", ""))
        elif t == "tool_use":
            flush_turn()
            name = e.get("toolName") or e.get("name") or "tool"
            inp = e.get("input") or {}
            if name == "retrieve":
                label = "🔍 retrieve"
                summary = f"“{esc((inp.get('query') or '')[:100])}”"
                extra = []
                if inp.get("fiscal_year"): extra.append(f"fy {inp['fiscal_year']}")
                if inp.get("doc_type"): extra.append(f"doc_type {inp['doc_type']}")
                if inp.get("agency_canonical_id"): extra.append(f"{inp['agency_canonical_id']}")
                body = ("".join(
                    f"<span class='chat-chip'>{esc(x)}</span>" for x in extra)
                    + (f"<pre>{esc(json.dumps(inp, ensure_ascii=False)[:800])}</pre>"
                       if not extra else ""))
            elif name in ("cite", "cite_batch"):
                cits = inp.get("citations") if isinstance(inp.get("citations"), list) else None
                first = (cits[0] if cits else inp)
                cid = first.get("chunk_id") or ""
                quote = (first.get("quote") or "")[:90]
                label = "📎 cite" + (" batch" if name == "cite_batch" else "")
                summary = f"{esc(str(cid))} · “{esc(quote)}…”"
                body = "".join(
                    f"<span class='chat-cite-pill is-verbatim'>{esc(c.get('chunk_id',''))[:14]}</span>"
                    for c in (cits or [])[:6])
            else:
                label = f"🛠 {esc(name)}"
                summary = ""
                body = f"<pre>{esc(json.dumps(inp, ensure_ascii=False)[:400])}</pre>"
            parts.append(f"<div class='chat-tool'><div class='chat-tool-head'>"
                         f"<span class='chat-tool-glyph'></span>"
                         f"<span class='chat-tool-label'>{label}</span>"
                         f"<span class='chat-tool-summary'>{summary}</span>"
                         f"</div><div class='chat-tool-body'>{body}</div></div>")
        elif t == "tool_result":
            res = e.get("output") or e.get("result") or ""
            s = str(res)
            ok = "ok" if not (isinstance(res, dict) and res.get("error")) else "error"
            parts.append(f"<div class='chat-tool is-inset{' is-failed' if ok=='error' else ''}'>"
                         f"<div class='chat-tool-head'><span class='chat-tool-label'>→ {esc(ok)}</span>"
                         f"<span class='chat-tool-summary'>{esc(s[:100])}{'…' if len(s)>100 else ''}</span>"
                         f"</div></div>")
    flush_turn()
    # NOTE: no separate "final answer" section — the last assistant delta
    # already carries the full final message, so a second rendering would
    # duplicate it. The terminal frame is only read for the run's state.
    return "\n".join(parts)


# ---------- judge ----------

def render_judge_html(judge: dict, qid: str) -> str:
    pq = next((q for q in judge.get("per_query", [])
               if q.get("query_id") == qid), None)
    if not pq:
        return "<p class='muted'>no judge review</p>"
    out = [f"<div class='metric-grid'>"]
    for k in JUDGE_KEYS:
        if k in pq:
            out.append(f"<div class='metric'><div class='k'>{esc(k)}</div>"
                       f"<div class='v'>{_fmt(pq[k])}</div></div>")
    out.append("</div>")
    if pq.get("chunk_relevance_rationale"):
        out.append(f"<p><strong>chunk relevance:</strong> {esc(pq['chunk_relevance_rationale'])}</p>")
    if pq.get("rationale"):
        out.append(f"<p><strong>rationale:</strong> {esc(pq['rationale'])}</p>")
    flags = pq.get("flags") or {}
    on = [k for k, v in flags.items() if v]
    if on:
        out.append(f"<p><span class='err'>flags: {esc(', '.join(on))}</span></p>")
    claims = pq.get("load_bearing_claims") or []
    if claims:
        out.append("<ul class='claims'>")
        for c in claims:
            mark = "✓" if c.get("cited_verified") else "✗"
            cls = "ok" if c.get("cited_verified") else "bad"
            out.append(f"<li><span class='{cls}'>{mark}</span> {esc(c.get('claim',''))}</li>")
        out.append("</ul>")
    return "\n".join(out)


# ---------- shared page chrome ----------

def nav_html(active: str) -> str:
    """Nav bar shared by every page: Latest Run Metrics | Per-Query | Historical."""
    items = [("index.html", "Latest Run Metrics", "index"),
             ("index.html#per-query", "Per-Query", "per-query"),
             ("historical.html", "Historical", "historical")]
    out = ["<nav class='nav'>"]
    for href, label, key in items:
        cls = " class='active'" if key == active else ""
        out.append(f"<a href='{href}'{cls}>{label}</a>")
    out.append("</nav>")
    return "".join(out)


def page(title: str, body: str, *, active: str = "index", back: str | None = None,
         sub: str = "") -> str:
    backhtml = f'<a class="back" href="{back}">← back to summary</a>' if back else ""
    subhtml = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<header><h1>{esc(title)}</h1>{subhtml}</header>
<script>{JS}</script>
<div class="wrap">{nav_html(active)}{backhtml}{body}</div></body></html>"""


def metric_card(label: str, v, *, tip: str = "", key: str = "") -> str:
    """A styled metric card; the .v element carries the (fixed) value color class.
    WHY a dedicated helper instead of inline f-strings: the color-coding bug
    (class='v class='warn'') came from pre-wrapping the class; centralizing
    keeps every caller on the safe path."""
    tipattr = f' data-tip="{esc(tip)}"' if tip else ""
    vcls = _metric_value_class(key, v)
    return (f"<div class='metric'{tipattr}><div class='k'>{esc(label)}</div>"
            f"<div{vcls}>{_fmt(v)}</div></div>")


def metric_group(title: str, cards: list[str]) -> str:
    return (f"<div class='metric-group'><h3>{esc(title)}</h3>"
            f"<div class='metric-grid'>{''.join(cards)}</div></div>")


# ---------- summary (index) page ----------

# Groups for the per-query metric grid (regrouped per Destin's request:
# accuracy / cost / efficiency, scannable instead of one wall of cards).
QUERY_METRIC_GROUPS = [
    ("Accuracy", [("accurate", "accurate"), ("key_fact_rate", "fact rate"),
                  ("ok", "ok"), ("verified_citations", "cites ok"),
                  ("cite_pass_rate", "cite pass"), ("figure_coverage", "fig cov")]),
    ("Cost", [("cost_usd", "cost"), ("total_tokens", "tokens")]),
    ("Efficiency", [("steps", "turns"), ("retrieve_call_count", "retrieves"),
                    ("retrieval_efficiency", "retr eff"),
                    ("first_try_cite_rate", "1st-try")]),
]
# Flatten the same set for the index table (avoids drift between the two).
INDEX_COLUMNS = [("query_id", "query"), ("shape", "shape"), ("set", "set")]
for _group, _cols in QUERY_METRIC_GROUPS:
    for k, label in _cols:
        if (k, label) not in INDEX_COLUMNS:
            INDEX_COLUMNS.append((k, label))
INDEX_COLUMNS += [("last_run_date", "last run"), ("run_id", "run")]


def _latest_run_metrics(data: dict) -> str:
    """Section A of the index: top-line metric cards for the MOST RECENT run."""
    run = _latest_run(data["runs"])
    if not run:
        return "<div class='summary-card'><h2>Latest Run Metrics</h2><p class='muted'>No runs found.</p></div>"
    scores = run["scores"]
    summary = scores.get("summary", {})
    judge = run["judge"]
    out = [f"<div class='summary-card'><h2>Latest Run Metrics</h2>"
           f"<p class='hint'>Run <code>{esc(run['run_id'])}</code> · "
           f"{esc(_fmt_date(run['timestamp']))}</p>"
           f"<div class='metric-grid'>"]
    for k, label in SUMMARY_KEYS:
        if k in summary:
            tip = STAT_HELP.get(label, "")
            out.append(metric_card(label, summary[k], tip=tip, key=k))
    for k in ["holistic_mean", "chunk_relevance_mean",
              "claim_coverage_precision_mean", "claim_coverage_recall_mean"]:
        if judge.get("summary", {}).get(k) is not None:
            label = k
            tip = STAT_HELP.get(k, STAT_HELP.get(k.replace("_mean", ""), ""))
            out.append(metric_card(label, judge["summary"][k], tip=tip, key=k))
    out.append("</div><p class='hint'>Hover any stat for what it means. "
               "Click a column to sort.</p></div>")
    return "\n".join(out)


def _per_query_table(data: dict) -> str:
    """Section B of the index: one row per query from its most recent run,
    plus a 'last run' date and run-id column."""
    latest_by_query = _query_latest_runs(data["runs"])
    if not latest_by_query:
        return "<h2 id='per-query'>Per-Query</h2><p class='muted'>No queries found.</p>"
    out = ["<h2 id='per-query'>Per-Query <span class='count'>hover a query to "
           "see its full question</span></h2>"
           "<div class='table-scroll'><table class='sortable'><thead><tr>"]
    for k, label in INDEX_COLUMNS:
        tip = STAT_HELP.get(label, "")
        tipattr = f' data-tip="{esc(tip)}"' if tip else ""
        out.append(f"<th{tipattr}>{label}<span class='sort'></span></th>")
    out.append("</tr></thead><tbody>")
    for qid in sorted(latest_by_query):
        run = latest_by_query[qid]
        r = _per_query_lookup(run["scores"]).get(qid, {})
        umsg = _user_message(run["dir"], qid)
        out.append("<tr>")
        for k, _label in INDEX_COLUMNS:
            if k == "query_id":
                tipattr = f' data-tip="{esc(umsg)}"' if umsg else ""
                out.append(f'<td><span class="tooltip-wrap"{tipattr}>'
                           f'<a class="query-chip" href="per-query/{esc(qid)}.html">'
                           f'{esc(qid)}</a></span></td>')
            elif k == "last_run_date":
                out.append(f"<td>{esc(_fmt_date(run['timestamp']))}</td>")
            elif k == "run_id":
                out.append(f"<td class='muted'>{esc(run['run_id'])}</td>")
            else:
                raw = r.get(k)
                v = _fmt(raw)
                cls = ""
                if k == "accurate":
                    cls = "class='ok'" if raw else "class='bad'"
                elif k == "ok" and raw is False:
                    cls = "class='bad'"
                elif k in ("key_fact_rate", "cite_pass_rate", "figure_coverage",
                           "retrieval_efficiency", "first_try_cite_rate"):
                    cls = f"class='{_metric_class(k, raw)}'" if raw is not None else ""
                else:
                    cls = ""
                out.append(f"<td {cls}>{esc(v)}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def _error_ledger(data: dict) -> str:
    """Tool-error ledger (from the LATEST run's errors.json)."""
    run = _latest_run(data["runs"])
    out = ["<h2>Tool errors</h2>"]
    if not run or not run["errors"]:
        out.append("<p class='muted'>No tool errors.</p>")
        return "\n".join(out)
    errs = run["errors"]
    by = Counter(e.get("kind") for e in errs)
    out.append("<table><tr><th>kind</th><th>count</th></tr>")
    for kind, n in by.most_common():
        out.append(f"<tr><td>{esc(kind)}</td><td>{n}</td></tr>")
    out.append("</table><ul>")
    for e in errs:
        out.append(f"<li><strong>{esc(e.get('query_id'))}</strong> turn "
                   f"{esc(e.get('turn'))}: {esc(e.get('kind'))} — "
                   f"{esc(str(e.get('detail'))[:160])}</li>")
    out.append("</ul>")
    return "\n".join(out)


def summary_page(results_root: Path, data: dict) -> str:
    latest = _latest_run(data["runs"])
    title = "Eval report — latest run metrics" if latest else "Eval report"
    sub = f"Most recent run: {esc(latest['run_id'])} · {esc(_fmt_date(latest['timestamp']))}" if latest else ""
    body = "\n".join([
        _latest_run_metrics(data),
        _per_query_table(data),
        _error_ledger(data),
        f"<p class='muted'>Report bundle · {len(data['runs'])} run(s) discovered "
        f"in {esc(str(results_root / 'agent'))}</p>",
    ])
    return page(title, body, active="index", sub=sub)


# ---------- per-query page ----------

def query_page(results_root: Path, data: dict, qid: str) -> str:
    """One page per query, backed by that query's MOST RECENT run."""
    latest_by_query = _query_latest_runs(data["runs"])
    run = latest_by_query.get(qid)
    if not run:
        return page(f"{qid} — not found",
                    "<p class='muted'>No run contains this query.</p>",
                    active="per-query", back="../index.html")
    r = _per_query_lookup(run["scores"]).get(qid, {})
    out = []
    # regrouped metric grid: accuracy / cost / efficiency
    for group, cols in QUERY_METRIC_GROUPS:
        cards = []
        for k, label in cols:
            if k in r:
                tip = STAT_HELP.get(label, "")
                cards.append(metric_card(label, r[k], tip=tip, key=k))
        if cards:
            out.append(metric_group(group, cards))
    if "accurate" in r and r.get("accurate") is not None:
        bcls = "good" if r["accurate"] else "bad"
        out.append(f"<span class='badge {bcls}'>"
                   f"{'✓ accurate' if r['accurate'] else '✗ NOT accurate'}</span>")
    out.append(f"<p class='hint'>Most recent run: <code>{esc(run['run_id'])}</code> · "
               f"{esc(_fmt_date(run['timestamp']))}</p>")
    out.append("<h2>Judge review</h2>")
    out.append(render_judge_html(run["judge"], qid))
    out.append("<h2>Conversation</h2>")
    out.append(render_chat_html(run["dir"], qid))
    out.append("<p class='muted'>raw transcript: "
               f"<code>per-query/{esc(qid)}.jsonl</code> · "
               f"<a href='historical.html'>history for this query</a></p>")
    return page(f"{qid} — eval report", "\n".join(out),
                active="per-query", back="../index.html")


# ---------- historical page ----------

# Metrics to chart over time on the top-line tab.
HISTORY_SUMMARY_KEYS = [
    ("accurate_rate", "accurate rate"),
    ("key_fact_rate_mean", "fact rate mean"),
    ("turns_to_accurate_mean", "turns/acc"),
    ("tokens_to_accurate_mean", "tokens/acc"),
    ("cite_pass_rate", "cite pass"),
    ("total_cost_usd", "total cost"),
    ("cost_mean_usd", "cost/query"),
    ("steps_mean", "turns mean"),
    ("retrieve_calls_mean", "retrieves mean"),
    ("retrieval_efficiency_mean", "retr eff mean"),
]
# Metrics to chart per query on the per-query tab.
HISTORY_QUERY_KEYS = [
    ("accurate", "accurate"), ("key_fact_rate", "fact rate"),
    ("cost_usd", "cost"), ("steps", "turns"),
    ("retrieve_call_count", "retrieves"), ("verified_citations", "cites ok"),
    ("figure_coverage", "fig cov"),
]


def history_page(results_root: Path, data: dict, tab: str = "topline") -> str:
    runs = data["runs"]
    out = []
    # tabs: BOTH contents are baked into the HTML so the browser can switch
    # without a server; a tiny script toggles them based on ?tab=.
    tabs = [("topline", "Top-line metrics"), ("per-query", "Per-query timeline")]
    out.append("<div class='tabs'>")
    for key, label in tabs:
        cls = " class='active'" if tab == key else ""
        out.append(f"<a href='historical.html?tab={key}' data-tab='{key}'{cls}>{label}</a>")
    out.append("</div>")
    out.append("<p class='hint'>Every run discovered in "
               f"<code>{esc(str(results_root / 'agent'))}</code>, oldest → "
               "newest. Blank cells = the metric wasn't collected in that run "
               "(schema changed 2026-08-17).</p>")
    topline_html = _history_topline(runs)
    perq_html = _history_per_query(runs)
    topline_cls = "" if tab == "topline" else " style='display:none'"
    perq_cls = "" if tab == "per-query" else " style='display:none'"
    out.append(f"<div id='tab-topline'{topline_cls}>{topline_html}</div>")
    out.append(f"<div id='tab-per-query'{perq_cls}>{perq_html}</div>")
    return page("Eval history — metrics over time", "\n".join(out),
                active="historical")


def _history_topline(runs: list[dict]) -> str:
    if not runs:
        return "<p class='muted'>No runs found.</p>"
    rows = []
    for key, label in HISTORY_SUMMARY_KEYS:
        cells = []
        blank = True
        for run in runs:
            v = run["scores"].get("summary", {}).get(key)
            if v is not None:
                cells.append(f"<td>{_fmt(v)}</td>")
                blank = False
            else:
                cells.append("<td class='muted'>—</td>")
        if not blank:
            tip = STAT_HELP.get(label, "")
            tipattr = f' data-tip="{esc(tip)}"' if tip else ""
            rows.append(f"<tr><th{tipattr}>{esc(label)}</th>{''.join(cells)}</tr>")
    head = "".join(f"<th>{esc(_fmt_date(r['timestamp']))}</th>" for r in runs)
    return (f"<h2>Top-line metrics over time</h2>"
            f"<div class='table-scroll'><table><thead><tr><th>metric</th>{head}</tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>")


def _history_per_query(runs: list[dict]) -> str:
    if not runs:
        return "<p class='muted'>No runs found.</p>"
    # index each query's rows by run timestamp for O(1) lookup when emitting
    by_q: dict[str, dict[str, dict]] = {}
    for run in runs:
        for r in run["scores"].get("per_query", []):
            by_q.setdefault(r["query_id"], {})[run["timestamp"]] = r
    head = "".join(f"<th>{esc(_fmt_date(r['timestamp']))}</th>" for r in runs)
    out = ["<h2>Per-query timeline</h2>"]
    for qid in sorted(by_q):
        entries_by_ts = by_q[qid]
        rows = []
        for key, label in HISTORY_QUERY_KEYS:
            cells = []
            blank = True
            # ALWAYS emit one cell per run so values line up under the right
            # date column; queries absent from a run show a blank. (The old
            # code emitted cells only for runs the query appeared in, so data
            # slid left and landed under the wrong dates.)
            for run in runs:
                r = entries_by_ts.get(run["timestamp"])
                v = r.get(key) if r else None
                if v is not None:
                    cells.append(f"<td>{_fmt(v)}</td>")
                    blank = False
                else:
                    cells.append("<td class='muted'>—</td>")
            if not blank:
                rows.append(f"<tr><th>{esc(label)}</th>{''.join(cells)}</tr>")
        out.append(f"<h3><a href='per-query/{esc(qid)}.html'>{esc(qid)}</a></h3>"
                   f"<div class='table-scroll'><table><thead><tr><th>metric</th>{head}</tr></thead>"
                   f"<tbody>{''.join(rows)}</tbody></table></div>")
    return "\n".join(out)


# ---------- build ----------

def build(run_dir: Path, *, no_open: bool = False) -> Path:
    """Build the report bundle for a SPECIFIC run.

    The index + historical pages are cross-run views: they discover every run
    under eval/results/agent/ so the "latest run" is always the true latest,
    even when an old run's report is being rebuilt. Per-query pages and the
    raw transcript copies are written inside this run's report dir.
    """
    results_root = run_dir.parent.parent
    data = _load_all(results_root)
    report = run_dir / "report"
    pq_dir = report / "per-query"
    raw_dir = report / "raw"
    pq_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    (report / "index.html").write_text(summary_page(results_root, data), encoding="utf-8")
    (report / "historical.html").write_text(
        history_page(results_root, data, tab="topline"), encoding="utf-8")
    # per-query pages: for each query in THIS run, render from its latest run
    run_scores = _load_run(run_dir)["scores"]
    qids = {r["query_id"] for r in run_scores.get("per_query", [])}
    for qid in sorted(qids):
        (pq_dir / f"{qid}.html").write_text(query_page(results_root, data, qid),
                                            encoding="utf-8")
        src = run_dir / f"{qid}-r1.jsonl"
        if src.exists():
            shutil.copy(src, pq_dir / f"{qid}.jsonl")
    for name in ("scores.json", "judge.json", "manifest.json", "errors.json",
                 "errors.md", "ledger.jsonl", "scores.md"):
        src = run_dir / name
        if src.exists():
            shutil.copy(src, raw_dir / name)
    print(f"report bundle written to {report}/")
    if not no_open:
        try:
            webbrowser.open(f"file://{report / 'index.html'}")
        except Exception:
            subprocess.Popen(["xdg-open", str(report / "index.html")])
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Build + open an HTML eval report bundle")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--no-open", action="store_true", help="build without launching a browser")
    args = ap.parse_args()
    build(args.run_dir, no_open=args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())