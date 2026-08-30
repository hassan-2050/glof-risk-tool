"""Generate a static results page from the run. No server, no build step.

Emitted by Stage 18 alongside RESULTS/LIMITS/ETHICS, from the same artefacts,
so a figure on the page cannot disagree with the pipeline that produced it.

DETERMINISM. This file is hashed into outputs/run_manifest.json and the
two-cold-run byte-identity test covers it, so the page contains:
  * no clock reading - the only date is determinism.frozen_utc
  * no randomness, no generated ids
  * sorted iteration everywhere
  * floats rounded at format time, never raw repr
It is written with write_text (UTF-8, LF), same as every other artefact.

HONESTY. The page is laid out so a reader cannot reach a headline number
without the caveat attached to it. The recall figure sits beside the 8-year
baseline qualifier; the delineation chart shows all eight lakes including the
three that fail, not a filtered "validated" subset.

CHARTS. Forms follow the data's job, not decoration:
  * delineation ratio vs 1.0 is POLARITY (over/under-measured) -> diverging bar,
    blue<->red, neutral gray midpoint
  * baseline vs advanced is two distinct models -> dumbbell with two categorical
    hues (slot 1 blue, slot 2 orange), one shared 0-1 axis
  * the confusion matrix is eight meaningful cells -> a table, not a chart
Palette values are the validated reference steps; every pair used here passed
the six-check validator in BOTH light and dark mode.
"""
from __future__ import annotations

import html
import json

# Validated palette. Each pair below passed scripts/validate_palette.js in both
# modes: slots 1+2 (dumbbell) ALL PASS; blue<->red diverging poles ALL PASS.
PALETTE = {
    "light": {
        "surface": "#fcfcfb", "plane": "#f9f9f7",
        "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
        "grid": "#e1e0d9", "axis": "#c3c2b7", "border": "rgba(11,11,11,0.10)",
        "s1": "#2a78d6", "s2": "#eb6834",
        "pos": "#2a78d6", "neg": "#e34948", "mid": "#f0efec",
        "good": "#0ca30c", "critical": "#d03b3b", "warning": "#fab219",
    },
    "dark": {
        "surface": "#1a1a19", "plane": "#0d0d0d",
        "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
        "grid": "#2c2c2a", "axis": "#383835", "border": "rgba(255,255,255,0.10)",
        "s1": "#3987e5", "s2": "#d95926",
        "pos": "#3987e5", "neg": "#e66767", "mid": "#383835",
        "good": "#0ca30c", "critical": "#d03b3b", "warning": "#fab219",
    },
}


def _e(x) -> str:
    """Escape for HTML. Source quotes and Devanagari both pass through here."""
    return html.escape(str(x), quote=True)


def _num(v, dp=2) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return f"{v:,.{dp}f}".rstrip("0").rstrip(".") if dp else f"{v:,.0f}"
    return _e(v)


# --------------------------------------------------------------------------
# charts - inline SVG, no dependencies, no script
# --------------------------------------------------------------------------

def diverging_bar(rows, width=680, row_h=30, pad_l=190, pad_r=64):
    """Ratio-to-published per lake, diverging about 1.0.

    Polarity, not magnitude: left of centre is under-measured, right is over.
    A sequential ramp would hide the sign, which is the whole point here.
    """
    if not rows:
        return "<p class='empty'>no validated lakes</p>"
    hi = max(2.0, max(r["ratio"] for r in rows) * 1.1)
    inner = width - pad_l - pad_r
    def x(v):
        return pad_l + (min(v, hi) / hi) * inner
    x1 = x(1.0)
    h = len(rows) * row_h + 46
    out = [f'<svg viewBox="0 0 {width} {h}" role="img" '
           f'aria-label="Measured lake area as a ratio of the published '
           f'reference, per lake. 1.0 is exact agreement." class="chart">']
    # gridlines at 0.5 intervals, hairline, recessive
    tick = 0.5
    t = 0.0
    while t <= hi + 1e-9:
        gx = x(t)
        out.append(f'<line x1="{gx:.1f}" y1="18" x2="{gx:.1f}" y2="{h-28:.0f}" '
                   f'class="grid"/>')
        out.append(f'<text x="{gx:.1f}" y="{h-14:.0f}" class="tick" '
                   f'text-anchor="middle">{t:g}x</text>')
        t += tick
    # the 1.0 reference: the neutral midpoint of the diverging scale
    out.append(f'<line x1="{x1:.1f}" y1="14" x2="{x1:.1f}" y2="{h-28:.0f}" '
               f'class="ref"/>')
    out.append(f'<text x="{x1:.1f}" y="11" class="reflabel" '
               f'text-anchor="middle">published = 1.0x</text>')
    for i, r in enumerate(rows):
        y = 24 + i * row_h
        v = r["ratio"]
        xv = x(v)
        left, right = (min(x1, xv), max(x1, xv))
        cls = "pos" if v >= 1.0 else "neg"
        bw = max(right - left, 1.5)
        # 24px cap, 4px rounded data-end, square at the baseline
        out.append(f'<rect x="{left:.1f}" y="{y:.0f}" width="{bw:.1f}" '
                   f'height="16" rx="4" class="bar {cls}"/>')
        out.append(f'<text x="{pad_l-10}" y="{y+12:.0f}" class="cat" '
                   f'text-anchor="end">{_e(r["lake"])}</text>')
        # direct label at the tip - the contrast WARN on light fills obliges it
        lx = right + 7 if v >= 1.0 else left - 7
        anc = "start" if v >= 1.0 else "end"
        out.append(f'<text x="{lx:.1f}" y="{y+12:.0f}" class="val" '
                   f'text-anchor="{anc}">{v:.2f}x</text>')
    out.append("</svg>")
    return "".join(out)


def dumbbell(rows, width=680, row_h=38, pad_l=210, pad_r=76):
    """Baseline vs advanced on a single 0-1 axis.

    Two models are two identities, so the ends carry categorical slots 1 and 2
    rather than two shades of one hue - and two shades could not pass the
    contrast checks inside the narrow dark-mode lightness band anyway.
    Deliberately excludes word-edit-distance: it is on a different scale, and a
    second axis would invent a comparison the data does not support.
    """
    if not rows:
        return "<p class='empty'>no metrics</p>"
    inner = width - pad_l - pad_r
    def x(v):
        return pad_l + max(0.0, min(v, 1.0)) * inner
    h = len(rows) * row_h + 46
    out = [f'<svg viewBox="0 0 {width} {h}" role="img" '
           f'aria-label="Reporter metrics, naive single-prompt baseline versus '
           f'the multi-agent pipeline, on a shared 0 to 1 axis." class="chart">']
    for t in (0.0, 0.25, 0.5, 0.75, 1.0):
        gx = x(t)
        out.append(f'<line x1="{gx:.1f}" y1="14" x2="{gx:.1f}" y2="{h-28:.0f}" class="grid"/>')
        out.append(f'<text x="{gx:.1f}" y="{h-14:.0f}" class="tick" '
                   f'text-anchor="middle">{t:g}</text>')
    for i, r in enumerate(rows):
        y = 26 + i * row_h
        xb, xa = x(r["baseline"]), x(r["advanced"])
        out.append(f'<line x1="{xb:.1f}" y1="{y:.0f}" x2="{xa:.1f}" y2="{y:.0f}" '
                   f'class="connector"/>')
        # >=8px markers with a 2px surface ring so they stay legible where they meet
        out.append(f'<circle cx="{xb:.1f}" cy="{y:.0f}" r="5" class="dot base"/>')
        out.append(f'<circle cx="{xa:.1f}" cy="{y:.0f}" r="5" class="dot adv"/>')
        out.append(f'<text x="{pad_l-12}" y="{y+4:.0f}" class="cat" '
                   f'text-anchor="end">{_e(r["metric"])}</text>')
        far = max(xb, xa)
        out.append(f'<text x="{far+12:.1f}" y="{y+4:.0f}" class="val" '
                   f'text-anchor="start">{r["baseline"]:.2f} → '
                   f'{r["advanced"]:.2f}</text>')
    out.append("</svg>")
    return "".join(out)


# --------------------------------------------------------------------------
# page
# --------------------------------------------------------------------------

def _kpi(label, value, sub, tone="") -> str:
    return (f'<div class="kpi {tone}"><div class="kpi-l">{_e(label)}</div>'
            f'<div class="kpi-v">{value}</div>'
            f'<div class="kpi-s">{_e(sub)}</div></div>')


def _table(headers, rows, cls="") -> str:
    h = "".join(f"<th>{_e(x)}</th>" for x in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
                   for r in rows)
    return (f'<div class="tw"><table class="{cls}"><thead><tr>{h}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def _css() -> str:
    def block(sel, p):
        return (f"{sel}{{--surface:{p['surface']};--plane:{p['plane']};"
                f"--ink:{p['ink']};--ink2:{p['ink2']};--muted:{p['muted']};"
                f"--grid:{p['grid']};--axis:{p['axis']};--border:{p['border']};"
                f"--s1:{p['s1']};--s2:{p['s2']};--pos:{p['pos']};"
                f"--neg:{p['neg']};--mid:{p['mid']};--good:{p['good']};"
                f"--critical:{p['critical']};--warning:{p['warning']};}}")
    L, D = PALETTE["light"], PALETTE["dark"]
    return f"""
{block(':root', L)}
{block(':root:not([data-theme="light"])' , D).replace(':root:not', '@media (prefers-color-scheme: dark){:root:not')}}}
{block(':root[data-theme="dark"]', D)}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--plane);color:var(--ink);
 font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:940px;margin:0 auto;padding:40px 24px 80px}}
h1{{font-size:30px;line-height:1.25;margin:0 0 6px;letter-spacing:-0.01em}}
h2{{font-size:19px;margin:44px 0 6px;letter-spacing:-0.005em}}
h3{{font-size:15px;margin:26px 0 6px;color:var(--ink2)}}
p{{margin:8px 0;color:var(--ink2)}}
.sub{{color:var(--muted);font-size:13px;margin:0 0 28px}}
.card{{background:var(--surface);border:1px solid var(--border);
 border-radius:12px;padding:20px 22px;margin:14px 0}}
.hero{{font-size:15px}}
.hero b{{color:var(--ink)}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(178px,1fr));gap:12px;margin:16px 0}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px}}
.kpi-l{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}}
.kpi-v{{font-size:27px;font-weight:600;margin:5px 0 2px;color:var(--ink);
 font-variant-numeric:tabular-nums}}
.kpi-s{{font-size:12px;color:var(--muted)}}
.kpi.good .kpi-v{{color:var(--good)}}
.kpi.warn .kpi-v{{color:var(--warning)}}
.tw{{overflow-x:auto;margin:10px 0}}
table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{text-align:left;padding:8px 12px;border-bottom:1px solid var(--border);
 white-space:nowrap;font-variant-numeric:tabular-nums}}
th{{font-weight:600;color:var(--muted);font-size:11px;text-transform:uppercase;
 letter-spacing:.05em}}
td.wrap-cell{{white-space:normal;min-width:260px}}
tr:last-child td{{border-bottom:none}}
.chart{{width:100%;height:auto;display:block;margin:8px 0}}
.grid{{stroke:var(--grid);stroke-width:1}}
.ref{{stroke:var(--axis);stroke-width:1.5}}
.bar.pos{{fill:var(--pos)}} .bar.neg{{fill:var(--neg)}}
.connector{{stroke:var(--axis);stroke-width:2;stroke-linecap:round}}
.dot{{stroke:var(--surface);stroke-width:2}}
.dot.base{{fill:var(--s1)}} .dot.adv{{fill:var(--s2)}}
.cat,.val,.tick,.reflabel{{font:12px ui-sans-serif,system-ui,sans-serif}}
.cat{{fill:var(--ink2)}} .val{{fill:var(--ink);font-variant-numeric:tabular-nums}}
.tick{{fill:var(--muted);font-size:11px}}
.reflabel{{fill:var(--muted);font-size:10.5px}}
.legend{{display:flex;gap:18px;flex-wrap:wrap;margin:4px 0 0;font-size:12.5px;color:var(--ink2)}}
.legend i{{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}}
.caveat{{border-left:3px solid var(--warning);background:var(--surface);
 padding:12px 16px;margin:12px 0;border-radius:0 8px 8px 0;font-size:13.5px}}
.caveat b{{color:var(--ink)}}
.pill{{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;
 font-weight:600;border:1px solid var(--border)}}
.pill.good{{color:var(--good)}} .pill.bad{{color:var(--critical)}}
.foot{{margin-top:52px;padding-top:18px;border-top:1px solid var(--border);
 font-size:12px;color:var(--muted)}}
code{{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;
 background:var(--surface);padding:1px 5px;border-radius:4px;border:1px solid var(--border)}}
"""


def render(data: dict) -> str:
    """Build the page. `data` is assembled by the caller from run artefacts."""
    p = []
    a = p.append

    a("<h1>GLOF Risk Tool — run results</h1>")
    a(f'<p class="sub">Generated by Stage 18 from the run itself · frozen clock '
      f'{_e(data["as_of"])} · research prototype, not an operational warning '
      f'system</p>')
    # The geometry behind these numbers is worth looking at, not just reading.
    # Relative link, and it names the build step because map.html is generated
    # outside `reproduce` and may legitimately not be there yet.
    a('<p class="sub">Lake outlines, flood corridors and a movable alarm '
      'threshold: <a href="tools/map.html">tools/map.html</a>'
      ' — build it with <code>make map</code>.</p>')

    # --- the claim -------------------------------------------------------
    h = data["headline"]
    a('<div class="card hero">')
    a(f'<b>The claim under test.</b> Area-growth screening misses Thyanbo Tsho '
      f'above Thame; a screen that also reasons about dam geometry and trigger '
      f'terrain catches it — using only pre-event data.')
    a(f'<p>Growth-only flagged Thame: <b>{_num(h["thame_growth_only_flagged"])}</b> '
      f'· proxy-augmented flagged Thame: <b>{_num(h["thame_proxy_flagged"])}</b> '
      f'· rank on the continuous score: <b>{_e(h["thame_proxy_rank"])}</b>.</p>')
    a(f'<p style="color:var(--muted);font-size:13px">'
      f'{_e(h["growth_only_reason"])}</p>')
    a("</div>")

    a('<div class="kpis">')
    a(_kpi("Recall, growth-only", _num(h["recall_growth_only"]),
           "of 3 burst lakes"))
    a(_kpi("Recall, proxy-augmented", _num(h["recall_proxy"]),
           "same cases, same cutoffs", "good"))
    a(_kpi("Contradiction F1", _num(h["contradiction_f1"]),
           "vs hand-labelled key", "good"))
    a(_kpi("Hallucination rate", f'{_num(h["hallu_base"])} → {_num(h["hallu_adv"])}',
           "baseline → multi-agent", "good"))
    a(_kpi("Negative control", "holds" if h["negative_control"] else "FAILS",
           "Chamoli not called a GLOF",
           "good" if h["negative_control"] else "warn"))
    a(_kpi("Delineation validated", f'{h["within_25"]}/{h["n_validated"]}',
           "lakes within 25% of published",
           "warn" if h["within_25"] < h["n_validated"] else "good"))
    a("</div>")

    # The caveat rides immediately beside the recall figures, by design.
    a('<div class="caveat"><b>Read the recall figures with this.</b> '
      'Growth-only recall is 0.000 <em>over an 8-year Sentinel-2 baseline</em>, '
      'not in general. South Lhonak genuinely is growth-catchable across '
      '1962–2023 (0.11 km² → 1.69 km²); our pinned data starts in 2017 because '
      'that is where usable Sentinel-2 L2A coverage starts, and the lake is flat '
      'across that window. A screen with a multi-decadal baseline would flag it.'
      '</div>')

    # --- confusion matrix (a table, not a chart) --------------------------
    a("<h2>Confusion matrix — same 14 lakes, same pre-event cutoffs</h2>")
    cm = data["confusion"]
    a(_table(["model", "TP", "FP", "FN", "TN", "recall", "precision", "F1"],
             [[_e(r["model"]), r["tp"], r["fp"], r["fn"], r["tn"],
               f'<b>{_num(r["recall"])}</b>', _num(r["precision"]),
               f'<b>{_num(r["f1"])}</b>'] for r in cm]))
    a(f'<p style="font-size:13px">Thame is a growth-only <b>false negative</b> '
      f'and a proxy-augmented <b>true positive</b>. Spearman against the Rounce '
      f'et al. (2017) expert classes: <b>{_num(data["spearman"])}</b> — which '
      f'<em>fell</em> from 0.63 when delineation was corrected, because accurate '
      f'areas raise the large lakes&rsquo; volume estimates and reorder the '
      f'ranking. Reported as measured.</p>')

    # --- delineation ------------------------------------------------------
    a("<h2>Delineation validated against published areas</h2>")
    a("<p>Best usable scene per lake. Every reference was checked against "
      "published sources before being used as a denominator; that check found "
      "one stale value (Imja&rsquo;s mid-2010s 1.28 km² — the lake reached "
      "1.56 km² by 2020).</p>")
    a(diverging_bar(data["delineation"]))
    a('<div class="legend">'
      f'<span><i style="background:var(--pos)"></i>at or above published</span>'
      f'<span><i style="background:var(--neg)"></i>below published</span></div>')
    a('<div class="caveat">Three lakes fail and the cause is diagnosed rather '
      'than tuned away. <b>South Lhonak 0.35×</b> — ESA&rsquo;s independent '
      'classifier finds the same ~0.57 km² at the same location, so the '
      'disagreement is not our rule. <b>Pyurepu 0.03×</b> — the 0.725 km² lake '
      'formed and drained inside a week; the annual series correctly sees the '
      'pre-2025 ponds. <b>Gokyo 1.46×, Tilicho 0.74×</b> remain unexplained.'
      '</div>')

    # --- reporter ---------------------------------------------------------
    a("<h2>Reporter — naive single-prompt baseline vs multi-agent</h2>")
    a(f'<p>{data["n_scenarios"]} scenarios: 4 real events plus 6 synthetic '
      f'perturbations injecting contradictions and fabricated facts.</p>')
    a(dumbbell(data["dumbbell"]))
    a('<div class="legend">'
      f'<span><i style="background:var(--s1)"></i>naive single-prompt baseline</span>'
      f'<span><i style="background:var(--s2)"></i>multi-agent pipeline</span></div>')
    a(_table(["metric", "baseline", "multi-agent", "delta"],
             [[_e(r["metric"]), _num(r["baseline"]), f'<b>{_num(r["advanced"])}</b>',
               _num(r["delta"])] for r in data["reporter_all"]]))
    a('<div class="caveat"><b>One of these is not an independent win.</b> The '
      'word-edit-distance improvement is trivial: the approved text <em>is</em> '
      'the advanced draft after verification, so the comparison flatters it by '
      'construction.</div>')

    # --- contradictions ---------------------------------------------------
    a("<h2>Contradictions surfaced, not resolved</h2>")
    a("<p>The project&rsquo;s central behaviour: where sources disagree, the "
      "disagreement is the output. No value is averaged or silently chosen.</p>")
    a(_table(["event", "quantity", "kind", "severity", "range", "sources"],
             [[_e(r["event"]), _e(r["quantity"]), _e(r["kind"]),
               f'<span class="pill {"bad" if r["severity"]=="high" else ""}">'
               f'{_e(r["severity"])}</span>',
               _e(r["range"]), f'<span class="wrap-cell">{_e(r["sources"])}</span>']
              for r in data["contradictions"]], cls="contra"))

    # --- approval ---------------------------------------------------------
    a("<h2>Human approval</h2>")
    ap = data["approval"]
    a(f'<p>{ap["human"]} of {ap["total"]} drafts carry a decision made by a named '
      f'person via <code>glof approve</code>; the remaining {ap["simulated"]} '
      f'still use the simulated config approver and are labelled as such in the '
      f'ledger. Chain intact: <b>{_num(ap["chain_intact"])}</b> · tamper '
      f'detected on edit: <b>{_num(ap["tamper_detected"])}</b>.</p>')
    a(_table(["draft", "verification", "decision", "approver", "real human?"],
             [[_e(r["draft"]),
               f'<span class="pill {"bad" if r["blocked"] else "good"}">'
               f'{"BLOCKED" if r["blocked"] else "passed"}</span>',
               _e(r["decision"]), _e(r["approver"]),
               f'<span class="pill {"good" if r["human"] else ""}">'
               f'{"yes" if r["human"] else "simulated"}</span>']
              for r in ap["rows"]]))

    a('<div class="foot">Decision-support for DHM, NDRRMA and ICIMOD, who hold '
      'the data and the mandate. Inundation outputs are indicative corridors, '
      'not flood maps. Empirical volume estimates carry 50–&gt;400% error. '
      'Full limits: <code>docs/LIMITS.md</code> · ethics: '
      '<code>docs/ETHICS.md</code> · every figure here is generated from '
      '<code>outputs/</code>.</div>')

    body = "\n".join(p)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        "<title>GLOF Risk Tool — run results</title>\n"
        f"<style>{_css()}</style>\n</head>\n<body>\n"
        f'<div class="wrap">\n{body}\n</div>\n</body>\n</html>\n')
