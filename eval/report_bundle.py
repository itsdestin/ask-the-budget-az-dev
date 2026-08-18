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
:root { --bg:#f7f8fa; --card:#fff; --ink:#1c2330; --muted:#5b6675;
        --accent:#2f6fda; --ok:#1a9d57; --bad:#d64545; --line:#e3e7ee; }
* { box-sizing:border-box; }
body { margin:0; font:15px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif;
       background:var(--bg); color:var(--ink); }
header { background:linear-gradient(135deg,#1c2b4a,#2f6fda); color:#fff;
         padding:26px 42px; }
header h1 { margin:0; font-size:22px; }
header .sub { opacity:.85; margin-top:4px; font-size:13px; }
.wrap { max-width:1200px; margin:0 auto; padding:26px 42px; }
h2 { margin-top:34px; font-size:19px; border-bottom:2px solid var(--line); padding-bottom:6px; }
table { border-collapse:collapse; width:100%; margin:14px 0; background:var(--card);
        box-shadow:0 1px 3px rgba(0,0,0,.06); border-radius:8px; overflow:hidden; }
th,td { padding:8px 11px; text-align:left; border-bottom:1px solid var(--line);
        font-size:13.5px; white-space:nowrap; }
th { background:#eef1f6; font-weight:600; }
tr:hover td { background:#f4f7fc; }
.ok { color:var(--ok); font-weight:700; } .bad { color:var(--bad); font-weight:700; }
.muted { color:var(--muted); }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:16px 20px; margin:12px 0; box-shadow:0 1px 3px rgba(0,0,0,.05); }
.metric-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; }
.metric { background:var(--card); border:1px solid var(--line); border-radius:8px;
          padding:10px 14px; }
.metric .k { font-size:11px; text-transform:uppercase; letter-spacing:.04em;
             color:var(--muted); }
.metric .v { font-size:18px; font-weight:700; margin-top:2px; }
.chat { border:1px solid var(--line); border-radius:10px; overflow:hidden; }
.msg { padding:12px 18px; border-bottom:1px solid var(--line); }
.msg.user { background:#eef3ff; }
.msg.assistant { background:#fff; }
.msg .who { font-size:11px; font-weight:700; text-transform:uppercase;
            letter-spacing:.05em; color:var(--muted); margin-bottom:4px; }
.msg .body { white-space:pre-wrap; }
.tool { background:#f2f5f9; border-left:3px solid var(--accent); padding:10px 16px;
        margin:8px 0; font-size:13.5px; }
.tool .tname { font-weight:700; }
.tool .tinput { margin-top:4px; font-family:ui-monospace,Monaco,monospace;
                font-size:12.5px; white-space:pre-wrap; color:#33415c; }
.tool .tresult { margin-top:4px; color:var(--muted); font-size:12.5px;
                 white-space:pre-wrap; font-family:ui-monospace,Monaco,monospace; }
.back { display:inline-block; margin-bottom:10px; color:var(--accent);
        text-decoration:none; font-weight:600; }
.err { color:var(--bad); }
.claims li { margin:3px 0; }
a { color:var(--accent); }
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

def page(title: str, body: str, *, back: str | None = None) -> str:
    backhtml = f'<a class="back" href="{back}">← back to summary</a>' if back else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>{esc(title)}</title><style>{CSS}</style></head><body>
<header><h1>{esc(title)}</h1></header>
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
            out.append(f"<div class='metric'><div class='k'>{esc(label)}</div>"
                       f"<div class='v'>{_fmt(summary[k])}</div></div>")
    for k in ["holistic_mean", "chunk_relevance_mean",
              "claim_coverage_precision_mean", "claim_coverage_recall_mean"]:
        if judge.get("summary", {}).get(k) is not None:
            out.append(f"<div class='metric'><div class='k'>{esc(k)}</div>"
                       f"<div class='v'>{_fmt(judge['summary'][k])}</div></div>")
    out.append("</div>")
    out.append("<h2>Per-query</h2><table><thead><tr>")
    for _, label in COLUMNS:
        out.append(f"<th>{label}</th>")
    out.append("</tr></thead><tbody>")
    for r in sorted(scores.get("per_query", []), key=lambda r: r["query_id"]):
        qid = r["query_id"]
        out.append("<tr>")
        for k, _ in COLUMNS:
            v = _fmt(r.get(k))
            cls = ""
            if k == "accurate" and r.get("accurate"):
                cls = "class='ok'"
            elif k == "accurate" and r.get("accurate") is False:
                cls = "class='bad'"
            elif k == "ok" and r.get("ok") is False:
                cls = "class='bad'"
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
            out.append(f"<div class='metric'><div class='k'>{esc(label)}</div>"
                       f"<div class='v'>{_fmt(r[k])}</div></div>")
    out.append("</div>")
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