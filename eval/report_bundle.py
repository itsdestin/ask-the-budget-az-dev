"""Assemble a run directory into a reviewable HTML report bundle.

Turns eval/results/agent/<run>/ (raw transcripts + scores + judge) into
eval/results/agent/<run>/report/ (a self-contained, styled, navigable
HTML site):

    index.html              the summary page: headline metrics + the full
                            per-query table (every output metric) + error
                            ledger, with one link per query
    per-query/<id>.html     one styled page per query: metrics, judge
                            review, and the conversation as it appeared in
                            the app (clean user/assistant messages, every
                            attempted tool call, final answer)
    per-query/<id>.jsonl    raw transcript copy for the exact record
    raw/                    copies of scores.json, judge.json, manifest.json

WHY styled HTML instead of markdown: Destin wants a report that LAUNCHES
at the end of a run and that he can navigate in a browser — a table of
every metric, the conversation per query as the app would have shown it
(no streaming-delta stutter), and the judge's verdict, readable without
any tool.

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

Free (no model calls) — reads the run dir only.
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

CSS = """
:root { --bg:#f6f8fb; --card:#fff; --ink:#161b26; --muted:#5c6775;
        --accent:#2563eb; --ok:#0e9f5b; --warn:#d97706; --bad:#dc2626;
        --line:#e5eaf1; --tool:#f1f5f9; --tool-edge:#93c5fd;
        --user-bubble:#eaf1ff; --assistant-bubble:#fff; --chip:#eef1f6; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { margin:0; font:15px/1.6 -apple-system,"Segoe UI",Roboto,sans-serif;
       background:var(--bg); color:var(--ink); }
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
  document.querySelectorAll(".msg .body").forEach(function (b) {
    b.innerHTML = md(b.textContent);
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
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    if isinstance(v, float):
        return f"{v:.{digits}g}"
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
        if x >= 0.5: return "warn"
        return "bad"
    # lower is better (turns, retrieves, cost, tokens) — only tint extremes
    if key in ("cost_usd", "total_cost_usd", "cost_mean_usd"):
        return "good" if x < 0.02 else ("warn" if x < 0.05 else "bad")
    return ""


def _load(run_dir: Path) -> dict:
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    judge = {}
    if (run_dir / "judge.json").exists():
        judge = json.loads((run_dir / "judge.json").read_text(encoding="utf-8"))
    errors = []
    if (run_dir / "errors.json").exists():
        errors = json.loads((run_dir / "errors.json").read_text(encoding="utf-8"))
    return {"scores": scores, "judge": judge, "errors": errors}


# ---------- conversation reconstruction ----------

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

    Reconstruction rule (verified against real transcripts): the assistant
    emits streamed deltas; some models re-emit growing prefixes, so the
    readable message is the LAST delta of a phase (it holds the full
    accumulated text). A tool call with NO preceding deltas means the model
    went straight to the tool. We therefore group: on user_message start a
    user bubble; accumulate deltas and, at a tool_use or turn boundary, emit
    the last delta as the assistant message; tool calls render as attempts.
    """
    evs = _conversation_events(run_dir, qid)
    if not evs:
        return "<p class='muted'>no transcript</p>"
    parts: list[str] = ["""<div class="chat">"""]
    cur_deltas: list[str] = []
    thinking = ""
    terminal = None

    def flush_message():
        nonlocal cur_deltas, thinking
        if cur_deltas:
            # last delta of the phase carries the full accumulated message
            text = cur_deltas[-1].strip()
            if text:
                parts.append(
                    f"<div class='msg assistant'><div class='who'>Assistant</div>"
                    f"<div class='body'>{esc(text)}</div></div>"
                )
            cur_deltas = []
        if thinking:
            parts.append(f"<div class='msg assistant'><div class='who'>Assistant · "
                         f"reasoning</div><div class='body muted'>{esc(thinking)}</div></div>")
            thinking = ""

    for e in evs:
        t = e.get("type")
        if t == "user_message":
            flush_message()
            parts.append(f"<div class='msg user'><div class='who'>User</div>"
                         f"<div class='body'>{esc(e.get('text',''))}</div></div>")
        elif t == "assistant_thinking":
            thinking = e.get("text") or thinking
        elif t == "assistant_text_delta":
            cur_deltas.append(e.get("text", ""))
        elif t == "tool_use":
            flush_message()
            name = e.get("toolName") or e.get("name") or "tool"
            inp = e.get("input") or {}
            parts.append(
                f"<div class='tool'><span class='tname'>{esc(name)}</span>"
                f"<div class='tinput'>{esc(json.dumps(inp, ensure_ascii=False, indent=1)[:600])}</div></div>"
            )
        elif t == "tool_result":
            res = e.get("output") or e.get("result") or ""
            s = str(res)
            parts.append(f"<div class='tool'><span class='tname'>→ result</span>"
                         f"<div class='tresult'>{esc(s[:400])}{'…' if len(s) > 400 else ''}</div></div>")
    flush_message()
    # terminal frame -> final answer
    for line in (run_dir / f"{qid}-r1.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "terminal":
            frame = rec.get("frame") or {}
            final = frame.get("finalAnswer")
            if final:
                parts.append(
                    f"<div class='msg assistant'><div class='who'>Final answer</div>"
                    f"<div class='body'>{esc(final)}</div></div>"
                )
    parts.append("</div>")
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


# ---------- pages ----------

def page(title: str, body: str, *, back: str | None = None, sub: str = "") -> str:
    backhtml = f'<a class="back" href="{back}">← back to summary</a>' if back else ""
    subhtml = f'<div class="sub">{esc(sub)}</div>' if sub else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<header><h1>{esc(title)}</h1>{subhtml}</header>
<script>{JS}</script>
<div class="wrap">{backhtml}{body}</div></body></html>"""


def summary_page(run_dir: Path, data: dict) -> str:
    scores = data["scores"]
    summary = scores.get("summary", {})
    judge = data.get("judge", {})
    out = []
    # headline summary
    out.append("<div class='metric-grid'>")
    for k, label in SUMMARY_KEYS:
        if k in summary:
            cls = _metric_class(k, summary[k])
            cls = f" class='{cls}'" if cls else ""
            out.append(f"<div class='metric'><div class='k'>{esc(label)}</div>"
                       f"<div class='v{cls}'>{_fmt(summary[k])}</div></div>")
    for k in ["holistic_mean", "chunk_relevance_mean",
              "claim_coverage_precision_mean", "claim_coverage_recall_mean"]:
        if judge.get("summary", {}).get(k) is not None:
            cls = _metric_class(k, judge["summary"][k])
            cls = f" class='{cls}'" if cls else ""
            out.append(f"<div class='metric'><div class='k'>{esc(k)}</div>"
                       f"<div class='v{cls}'>{_fmt(judge['summary'][k])}</div></div>")
    out.append("</div>")
    out.append("<h2>Per-query</h2>"
               "<table class='sortable'><thead><tr>")
    for _, label in COLUMNS:
        out.append(f"<th>{label}<span class='sort'></span></th>")
    out.append("</tr></thead><tbody>")
    for r in sorted(scores.get("per_query", []), key=lambda r: r["query_id"]):
        qid = r["query_id"]
        out.append("<tr>")
        for k, _ in COLUMNS:
            raw = r.get(k)
            v = _fmt(raw)
            cls = ""
            if k == "accurate":
                cls = "class='ok'" if raw else "class='bad'"
            elif k == "ok" and raw is False:
                cls = "class='bad'"
            elif k == "key_fact_rate" and raw is not None:
                cls = f"class='{_metric_class(k, raw)}'"
            if k == "query_id":
                out.append(f'<td><a href="per-query/{esc(qid)}.html">{esc(v)}</a></td>')
            else:
                out.append(f"<td {cls}>{esc(v)}</td>")
        out.append("</tr>")
    out.append("</tbody></table>")
    # errors
    errs = data.get("errors") or []
    out.append("<h2>Tool errors</h2>")
    if not errs:
        out.append("<p class='muted'>No tool errors.</p>")
    else:
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
    out.append(f"<p class='muted'>run {esc(run_dir.name)} · "
               f"report generated {(run_dir / 'scores.json').stat().st_mtime:.0f}</p>")
    return page(f"Eval report — {run_dir.name}", "\n".join(out))


def query_page(run_dir: Path, data: dict, qid: str) -> str:
    scores = data["scores"]
    r = next((x for x in scores.get("per_query", []) if x["query_id"] == qid), {})
    out = ["<div class='metric-grid'>"]
    for k, label in COLUMNS:
        if k in r and k != "query_id":
            cls = _metric_class(k, r[k])
            cls = f" class='{cls}'" if cls else ""
            out.append(f"<div class='metric'><div class='k'>{esc(label)}</div>"
                       f"<div class='v{cls}'>{_fmt(r[k])}</div></div>")
    out.append("</div>")
    if "accurate" in r and r.get("accurate") is not None:
        bcls = "good" if r["accurate"] else "bad"
        out.append(f"<span class='badge {bcls}'>"
                   f"{'✓ accurate' if r['accurate'] else '✗ NOT accurate'}</span>")
    out.append("<h2>Judge review</h2>")
    out.append(render_judge_html(data.get("judge", {}), qid))
    out.append("<h2>Conversation</h2>")
    out.append(render_chat_html(run_dir, qid))
    out.append("<p class='muted'>raw transcript: "
               f"<code>per-query/{esc(qid)}.jsonl</code></p>")
    return page(f"{qid} — eval report", "\n".join(out),
                back="index.html")


def build(run_dir: Path, *, no_open: bool = False) -> Path:
    data = _load(run_dir)
    report = run_dir / "report"
    pq_dir = report / "per-query"
    raw_dir = report / "raw"
    pq_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    (report / "index.html").write_text(summary_page(run_dir, data), encoding="utf-8")
    scores = data["scores"]
    for r in scores.get("per_query", []):
        qid = r["query_id"]
        (pq_dir / f"{qid}.html").write_text(query_page(run_dir, data, qid),
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