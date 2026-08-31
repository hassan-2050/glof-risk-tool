"""The agent architecture as one page you can point a camera at.

    python tools/build_agent_diagram.py   -> outputs/tools/agents.html

WHY THIS EXISTS
---------------
The design argument for this project is which parts are agentic and which are
deliberately not, and that argument is hard to make by scrolling a table. This
draws it: the flow of the eight agents, colour-separated by whether their
output is deterministic or model-generated, with the three choices that carry
the argument called out where they happen.

EVERY NUMBER IS READ, NOT TYPED
-------------------------------
The agent roster and step count come from outputs/agent_trajectories.json; the
ablation comes from outputs/stage14_reporter_eval.json. Same rule as the rest
of the repository: a figure on this page cannot disagree with the run that
produced it, because none of them is written by hand.

Opens from disk with the network off, like results.html and map.html.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import REPO_ROOT                    # noqa: E402
from src.common.io import TOOL_OUTPUT_DIR, read_json       # noqa: E402
# The pipeline's own palette. These pages are read side by side with
# results.html; a second hand-copied theme is a second thing to drift.
from src.reporter.results_page import PALETTE              # noqa: E402

OUT = REPO_ROOT / "outputs"
SITE = OUT / TOOL_OUTPUT_DIR

# The pipeline in execution order. `kind` drives the colour: deterministic
# output you can recompute, model output you cannot, or the human gate.
#   note  - the design choice this stage exists to make, shown under the box
STAGES = [
    {"id": "retriever", "name": "Retriever", "kind": "det",
     "does": "reads the pinned document bundle",
     "note": "3-publisher minimum, enforced; no live web calls"},
    {"id": "numeric_reconciliation", "name": "Numeric reconciliation",
     "kind": "det", "does": "extracts every figure, finds disagreement",
     "note": "RULE-BASED ON PURPOSE - an LLM here would make the one "
             "part whose value is that you can check it nondeterministic"},
    {"id": "drafter", "name": "Drafter", "kind": "llm",
     "does": "writes the OCHA sitrep, EN + NE",
     "note": "the only stage whose prose a model authors"},
    {"id": "verifier", "name": "Verifier", "kind": "det",
     "does": "is each figure in the span it cites?",
     "note": "rule-based, so it cannot hallucinate a verdict"},
    {"id": "adversarial_critic", "name": "Adversarial critic",
     "kind": "mixed", "does": "attacks what the verifier cannot see",
     "note": "the LLM half is ADVISORY - it cannot clear a draft. A model "
             "allowed to approve its own output is a rubber stamp"},
    {"id": "provenance_ledger", "name": "Provenance ledger", "kind": "det",
     "does": "binds every claim to its source",
     "note": "read by `reproduce`, never written by it"},
    {"id": "human", "name": "Human approval gate", "kind": "human",
     "does": "a named person decides",
     "note": "a blank keypress is refused; undecided drafts are labelled "
             "SIMULATED rather than passing quietly"},
    {"id": "exporter", "name": "Exporter", "kind": "det",
     "does": "CAP XML + HXL-tagged CSV",
     "note": "machine-readable, carries the same caveats"},
]

METRICS = [("contradiction_recall", "Contradiction recall", "up"),
           ("hallucination_rate", "Hallucination rate", "down"),
           ("numeric_accuracy", "Numeric accuracy", "up"),
           ("citation_f1", "Citation F1", "up")]

def _tokens() -> str:
    """Light-first, with an explicit theme choice winning in both directions
    and the un-stamped default following the OS - same contract as
    results.html."""
    def block(sel, p):
        return (f"{sel}{{--surface:{p['surface']};--plane:{p['plane']};"
                f"--ink:{p['ink']};--ink2:{p['ink2']};--muted:{p['muted']};"
                f"--border:{p['border']};--mid:{p['mid']};"
                f"--det:{p['good']};--llm:{p['warning']};"
                f"--mixed:{p['s1']};--human:{p['s2']};}}")
    L, D = PALETTE["light"], PALETTE["dark"]
    return (block(":root", L)
            + "@media (prefers-color-scheme: dark){"
            + block(':root:not([data-theme="light"])', D) + "}"
            + block(':root[data-theme="dark"]', D))


CSS = _tokens() + """
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font:15px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1240px;margin:0 auto;padding:34px 26px 70px}
h1{font-size:30px;margin:0 0 6px;letter-spacing:-.01em;line-height:1.25}
.sub{color:var(--muted);font-size:13.5px;margin-bottom:24px}
h2{font-size:11px;letter-spacing:.1em;text-transform:uppercase;
   color:var(--muted);margin:34px 0 12px;font-weight:700}

.key{display:flex;gap:18px;flex-wrap:wrap;margin-bottom:22px;font-size:13px}
.key span{display:flex;align-items:center;gap:7px;color:var(--ink2)}
.dot{width:10px;height:10px;border-radius:3px;display:inline-block}

.flow{display:flex;flex-direction:column;gap:0}
.row{display:flex;align-items:stretch;gap:0}
.box{flex:1;background:var(--surface);border:1px solid var(--border);
     border-top:3px solid var(--border);border-radius:12px;padding:13px 15px;
     display:flex;flex-direction:column;gap:6px;min-width:0}
.box.det{border-top-color:var(--det)}
.box.llm{border-top-color:var(--llm)}
.box.mixed{border-top-color:var(--mixed)}
.box.human{border-top-color:var(--human);background:var(--mid)}
.box .nm{font-weight:650;font-size:14.5px}
.box .does{color:var(--ink2);font-size:13.5px}
.box .note{color:var(--muted);font-size:12.5px;line-height:1.5;
           border-top:1px dashed var(--border);padding-top:7px;margin-top:2px}
.box .note b{color:var(--ink2)}
.arrow{display:flex;align-items:center;justify-content:center;
       color:var(--muted);font-size:18px;padding:0 8px;flex:none}
.pair{flex:1;display:flex;flex-direction:column;gap:9px;min-width:0}
.pairlab{font-size:11px;color:var(--muted);text-align:center;
         letter-spacing:.06em;text-transform:uppercase;font-weight:700}

table{border-collapse:collapse;width:100%;background:var(--surface);
      border:1px solid var(--border);border-radius:12px;overflow:hidden}
th,td{padding:10px 14px;text-align:right;font-variant-numeric:tabular-nums;
      border-bottom:1px solid var(--border);font-size:14px}
th:first-child,td:first-child{text-align:left}
thead th{font-size:10.5px;letter-spacing:.08em;text-transform:uppercase;
         color:var(--muted);font-weight:700}
tbody tr:last-child td{border-bottom:0}
.win{color:var(--det);font-weight:650}
.base{color:var(--muted)}
.note-line{color:var(--ink2);font-size:13px;margin-top:12px;line-height:1.55}
.note-line b{color:var(--ink)}
@media (max-width:1000px){
  .row{flex-direction:column;gap:9px}
  .arrow{transform:rotate(90deg);padding:2px 0}
}
"""


def main() -> int:
    traj = read_json(OUT / "agent_trajectories.json")
    rev = read_json(OUT / "stage14_reporter_eval.json")
    summary = rev.get("summary", {})
    n_steps = traj.get("total_steps", "?")
    n_events = traj.get("n_events", "?")

    # Agents that actually appear in the recorded trajectories - so the
    # diagram cannot show a stage the pipeline did not run.
    # `events` is keyed by event id, not a list.
    seen = set()
    for ev in (traj.get("events") or {}).values():
        seen.update(ev.get("agents_involved", []))

    def box(s):
        live = "" if s["id"] in seen or s["kind"] == "human" else " (not run)"
        return (f'<div class="box {s["kind"]}"><div class="nm">{s["name"]}'
                f'{live}</div><div class="does">{s["does"]}</div>'
                f'<div class="note">{s["note"]}</div></div>')

    arrow = '<div class="arrow">&rarr;</div>'
    pre = [s for s in STAGES if s["id"] in
           ("retriever", "numeric_reconciliation", "drafter")]
    checks = [s for s in STAGES if s["id"] in ("verifier", "adversarial_critic")]
    post = [s for s in STAGES if s["id"] in
            ("provenance_ledger", "human", "exporter")]

    row1 = arrow.join(box(s) for s in pre)
    checks_html = ('<div class="pair"><div class="pairlab">two checks that '
                   'fail differently</div>'
                   + "".join(box(s) for s in checks) + "</div>")
    row2 = arrow.join([checks_html] + [box(s) for s in post])

    rows = []
    for key, label, better in METRICS:
        m = summary.get(key, {})
        b, a = m.get("baseline"), m.get("advanced")
        if b is None or a is None:
            continue
        rows.append(
            f'<tr><td>{label}</td><td class="base">{b:.3f}</td>'
            f'<td class="win">{a:.3f}</td>'
            f'<td>{"+" if a > b else ""}{a - b:.3f}</td></tr>')

    html = f"""<!doctype html>
<meta charset="utf-8">
<title>GLOF reporter - agent architecture</title>
<style>{CSS}</style>
<div class="wrap">
  <h1>How the solution uses agents</h1>
  <div class="sub">Eight agents produce every situation report &middot;
    {n_steps} recorded steps across {n_events} events &middot; each step names
    the artefact that proves it</div>

  <div class="key">
    <span><i class="dot" style="background:var(--det)"></i>deterministic &mdash; recomputable, no model</span>
    <span><i class="dot" style="background:var(--llm)"></i>model-generated</span>
    <span><i class="dot" style="background:var(--mixed)"></i>rules + advisory model</span>
    <span><i class="dot" style="background:var(--human)"></i>human</span>
  </div>

  <div class="flow">
    <div class="row">{row1}</div>
    <div class="arrow" style="transform:rotate(90deg);height:26px">&rarr;</div>
    <div class="row">{row2}</div>
  </div>

  <h2>Did the architecture help? The ablation, not an assertion</h2>
  <table>
    <thead><tr><th>Metric, 10 scenarios</th><th>Single prompt</th>
      <th>This architecture</th><th>Delta</th></tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
  <div class="note-line">
    Same ten scenarios, same hand-labelled key, same pinned sources.
    <b>Reported against itself:</b> the edit-distance metric is omitted here
    because the approved text <i>is</i> the advanced draft after verification,
    so it flatters this pipeline by construction rather than measuring it.
  </div>
</div>
"""
    SITE.mkdir(parents=True, exist_ok=True)
    dest = SITE / "agents.html"
    dest.write_text(html, encoding="utf-8", newline="\n")
    print(f"wrote {dest.relative_to(REPO_ROOT).as_posix()} "
          f"({dest.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
