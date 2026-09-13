"""Renders the run as a single self-contained HTML page. Computes nothing."""

from __future__ import annotations

import html
import json
from typing import Any

from .config import RUNS

CSS = """
/* charcoal + cream. one accent, everything else tonal. */
:root{--bg:#F4F1EA;--panel:#FBF9F4;--panel2:#EAE5DA;--ink:#16150F;--ink2:#4A4740;--ink3:#7C776C;
--rule:#DCD6C8;--rule2:#C6BFAE;--accent:#16150F;
--pass-bg:#EAE5DA;--pass-ink:#5A564B;--fail-bg:#16150F;--fail-ink:#F4F1EA;--reg:#8C3A1E;
--mono:"JetBrains Mono",ui-monospace,Menlo,monospace;--ui:"Archivo","Helvetica Neue",Arial,sans-serif}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#0B0B0A;--panel:#141412;--panel2:#1F1E1B;
--ink:#F2EFE6;--ink2:#A8A399;--ink3:#78736A;--rule:#2A2926;--rule2:#3C3A35;--accent:#F2EFE6;
--pass-bg:#1F1E1B;--pass-ink:#8B867B;--fail-bg:#F2EFE6;--fail-ink:#0B0B0A;--reg:#D4703F}}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font-family:var(--ui);font-size:14px;line-height:1.5;margin:0}
.wrap{max-width:64rem;margin:0 auto;padding:2rem 1.25rem 5rem;display:flex;flex-direction:column;gap:1.25rem}
.bar{background:var(--panel);border:1px solid var(--rule);border-radius:2px;padding:1rem 1.15rem;
display:flex;flex-wrap:wrap;gap:1rem;align-items:center;justify-content:space-between}
.bar b{font-size:1.125rem;letter-spacing:-.02em;font-weight:700}
.bar .sub{font-family:var(--mono);font-size:.6875rem;color:var(--ink3);letter-spacing:.02em}
.stats{display:flex;flex-wrap:wrap;gap:.4rem}
.stat{font-family:var(--mono);font-size:.6875rem;padding:.3rem .55rem;border:1px solid var(--rule);
border-radius:2px;color:var(--ink2);white-space:nowrap}
.stat b{color:var(--ink);font-weight:700}
.stat.ok{border-color:var(--rule2)}
.stat.bad{border-color:var(--reg)}.stat.bad b{color:var(--reg)}
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:2px}
.ph{padding:.85rem 1.15rem;border-bottom:1px solid var(--rule);display:flex;justify-content:space-between;
gap:1rem;flex-wrap:wrap;align-items:baseline}
.ph h2{margin:0;font-size:.875rem;font-weight:700;letter-spacing:-.005em}
.ph p{margin:0;font-family:var(--mono);font-size:.6875rem;color:var(--ink3)}
.mw{overflow-x:auto;padding:1rem .8rem 1.1rem}
table.m{border-collapse:separate;border-spacing:2px;font-family:var(--mono)}
table.m th.v{font-size:.625rem;color:var(--ink3);padding-bottom:.35rem;letter-spacing:.08em}
table.m th.c{text-align:left;font-weight:400;font-size:.6875rem;color:var(--ink2);padding-right:1rem;white-space:nowrap}
.cell{width:2.2rem;height:1.7rem;border-radius:1px;font-size:.6875rem;font-weight:700;
display:flex;align-items:center;justify-content:center}
.p{background:var(--pass-bg);color:var(--pass-ink)}
.f{background:var(--fail-bg);color:var(--fail-ink)}
.r{background:var(--fail-bg);color:var(--fail-ink);box-shadow:inset 0 0 0 2px var(--reg)}
.legend{display:flex;flex-wrap:wrap;gap:1.1rem;padding:0 1.15rem 1.1rem;font-size:.6875rem;
color:var(--ink2);font-family:var(--mono)}
.legend i{width:.85rem;height:.85rem;border-radius:1px;display:inline-block;vertical-align:-2px;margin-right:.4rem}
table.t{width:100%;border-collapse:collapse;font-size:.75rem}
table.t th{text-align:left;font-family:var(--mono);font-size:.625rem;text-transform:uppercase;letter-spacing:.1em;
color:var(--ink3);padding:.6rem .8rem;border-bottom:1px solid var(--rule2);font-weight:700}
table.t td{padding:.6rem .8rem;border-bottom:1px solid var(--rule);vertical-align:top}
table.t tr:last-child td{border-bottom:0}
.mono{font-family:var(--mono);font-size:.6875rem}
.chip{font-family:var(--mono);font-size:.5625rem;padding:.15rem .4rem;border:1px solid var(--rule2);
border-radius:1px;color:var(--ink2);letter-spacing:.08em}
.chip.fix{border-color:var(--reg);color:var(--reg);font-weight:700}
.note{padding:1rem 1.15rem;font-size:.75rem;color:var(--ink2);line-height:1.65;border-top:1px solid var(--rule)}
.note b{color:var(--ink);font-weight:600}
.said{color:var(--ink2);max-width:32rem;white-space:pre-wrap}
.who{font-family:var(--mono);font-size:.625rem;color:var(--ink3);margin-top:.3rem}
a{color:inherit;text-decoration:none}
.live{background:var(--fail-bg);color:var(--fail-ink);border:1px solid var(--rule2);border-radius:2px;
padding:.7rem 1.15rem;font-family:var(--mono);font-size:.75rem;display:flex;align-items:center;gap:.6rem}
.live i{width:.5rem;height:.5rem;border-radius:50%;background:var(--reg);display:inline-block;
animation:pulse 1.2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
"""


def render(m: dict[str, Any], payload: dict, validation: dict, ex_stats: dict,
           candidates: dict | None = None, live: dict | None = None) -> str:
    """`live` is {"done": 3, "total": 5, "version": "v3"} while a run is still
    going, and None on the final write — which is what removes both the banner
    and the auto-refresh, so a finished report stops reloading itself."""
    vs = m["versions"]
    rows = m["rows"]
    pv = m["per_version"]
    total_reg = sum(len(x["regressions"]) for x in pv)
    agree = validation.get("agreement")
    agree_txt = f"{agree:.0%}" if isinstance(agree, float) else "n/a"

    head = "".join(f'<th class="v">{html.escape(v)}</th>' for v in vs)
    body = ""
    for r in rows:
        cells = "".join(
            f'<td><div class="cell {s}" title="{html.escape(r["reasons"][i][:120])}">'
            f'{"✓" if s == "p" else "✗"}</div></td>'
            for i, s in enumerate(r["states"]))
        fix = ' <span class="chip fix">from fix</span>' if r["from_fix"] else ""
        body += (f'<tr><th class="c">{html.escape(r["rule"])} · {html.escape(r["brief"])}'
                 f'{fix}</th>{cells}</tr>')

    scores = "  ·  ".join(f'{x["version"]} {x["score"]:.2f}' for x in pv)

    src_rows = ""
    seen = set()
    for r in rows:
        if r["rule"] in seen:
            continue
        seen.add(r["rule"])
        app = html.escape(r.get("source_app", "")).upper()
        chip = f'<span class="chip">{app}</span>'
        if r.get("source_url"):
            chip = f'<a href="{html.escape(r["source_url"])}">{chip}</a>'
        fix = ' <span class="chip fix">from fix</span>' if r["from_fix"] else ""
        said = html.escape((r.get("source_text") or "").strip()[:240])
        who = html.escape(r.get("source_author") or "")
        src_rows += (
            f'<tr><td>{chip}{fix}</td>'
            f'<td class="mono">{html.escape(r["rule"])}</td>'
            f'<td>{html.escape(r["title"])}</td>'
            f'<td class="said">{said or "<em>no source recorded</em>"}'
            f'{f"<div class=who>— {who}</div>" if who else ""}</td></tr>')

    cand_html = ""
    if candidates:
        crows = "".join(
            f'<tr><td class="mono">{html.escape(c["name"])}</td>'
            f'<td class="mono">+{c["fixes"]}</td><td class="mono">-{c["breaks"]}</td>'
            f'<td class="mono">{c["net"]:+d}</td><td>{html.escape(c["note"])}</td></tr>'
            for c in candidates["rows"])
        cand_html = f"""
<div class="panel"><div class="ph"><h2>Parallel candidates</h2>
<p>each run independently, then combined</p></div>
<table class="t"><thead><tr><th>change</th><th>fixes</th><th>breaks</th><th>net</th><th>note</th></tr></thead>
<tbody>{crows}</tbody></table>
<div class="note"><b>Effects are not additive.</b> Two changes that each help can break each
other, and nothing in their individual profiles predicts it — the combination has to be run.</div></div>"""

    refresh = '<meta http-equiv="refresh" content="2">' if live else ""
    banner = ""
    if live:
        banner = (f'<div class="live"><i></i>run in progress — {html.escape(live["version"])} '
                  f'of {live["total"]} · {live["done"]} version(s) scored so far</div>')

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{refresh}
<title>Ratchet — run report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap">
<style>{CSS}</style></head><body><div class="wrap">
{banner}
<div class="bar">
  <div><b>Ratchet</b> <span class="sub">engagement-letter generator · {len(rows)} cases · {len(vs)} versions</span></div>
  <div class="stats">
    <div class="stat ok">judge agreement <b>{agree_txt}</b> (n={validation.get('n', 0)})</div>
    <div class="stat">cases from <b>{ex_stats.get('rules', 0)}</b> rules · <b>{ex_stats.get('items', 0)}</b> items read</div>
    <div class="stat {'bad' if total_reg else ''}">regressions <b>{total_reg}</b></div>
    <div class="stat">run <b>{payload.get('seconds', 0)}s</b> · cache hits <b>{payload.get('llm', {}).get('hits', 0)}</b></div>
  </div>
</div>

<div class="panel">
  <div class="ph"><h2>Case × version</h2><p>{scores}</p></div>
  <div class="mw"><table class="m"><thead><tr><th></th>{head}</tr></thead><tbody>{body}</tbody></table></div>
  <div class="legend">
    <span><i style="background:var(--goodbg);box-shadow:inset 0 0 0 1px var(--good)"></i>passes</span>
    <span><i style="background:var(--badbg);box-shadow:inset 0 0 0 1px var(--bad)"></i>fails</span>
    <span><i style="background:var(--badbg);box-shadow:inset 0 0 0 2px var(--bad)"></i>regression — passed in the previous version</span>
  </div>
  <div class="note"><b>Aggregate score moves very little across versions.</b> The outlined cells are
  what a single number hides: a change that fixes one rule and silently breaks another nets out to
  roughly nothing, which reads as noise and sends you round the loop again.</div>
</div>

<div class="panel">
  <div class="ph"><h2>Where the cases came from</h2><p>{ex_stats.get('items', 0)} items read · {ex_stats.get('accepted', 0)} checkable · {ex_stats.get('not_checkable', 0)} discarded as chatter</p></div>
  <table class="t"><thead><tr><th>source</th><th>rule</th><th>failure</th><th>what someone actually said</th></tr></thead>
  <tbody>{src_rows}</tbody></table>
  <div class="note">Nothing here was hand-written as a test. Each rule was derived from a message,
  a ticket or a commit that a person produced in the course of their work.</div>
</div>
{cand_html}
</div></body></html>"""


def write(m, payload, validation, ex_stats, candidates=None, live=None) -> str:
    path = RUNS / "report.html"
    path.write_text(render(m, payload, validation, ex_stats, candidates, live))
    return str(path)
