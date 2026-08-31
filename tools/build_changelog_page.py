"""Render the generated changelog as a page, for reading and for filming.

    python tools/build_changelog_page.py  -> outputs/tools/changelog.html

WHY A RENDERER AND NOT A SECOND GENERATOR
-----------------------------------------
`CHANGELOG_improvements.md` is written by Stage 18 from the run. This reads
THAT file and gives it structure - hypothesis, change, result and evidence as
distinct blocks rather than four bold runs in a paragraph - so the iteration
loop is legible at a glance.

It deliberately does not recompute anything. A second generator reading the
same artefacts could drift from the first; a renderer cannot, because if the
markdown is wrong this page is wrong in exactly the same way.

Opens from disk with the network off, like results.html and map.html.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import REPO_ROOT                    # noqa: E402
from src.common.io import TOOL_OUTPUT_DIR                  # noqa: E402

SRC = REPO_ROOT / "CHANGELOG_improvements.md"
SITE = REPO_ROOT / "outputs" / TOOL_OUTPUT_DIR

FIELDS = ("Hypothesis", "Change", "Result", "Evidence")

CSS = """
:root{
  --bg:#0e1013; --panel:#15181d; --panel2:#1b1f26; --line:#272c35;
  --ink:#e8eaed; --ink2:#a6adba; --ink3:#6f7784;
  --hyp:#7c5cff; --chg:#3fa7ff; --res:#4ade80; --evi:#6f7784; --tool:#fbbf24;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14.5px/1.6 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1000px;margin:0 auto;padding:26px 26px 80px}
h1{font-size:22px;margin:0 0 6px;font-weight:680;letter-spacing:-.01em}
.lede{color:var(--ink2);font-size:13.5px;max-width:78ch;margin-bottom:8px}
.lede b{color:var(--ink)}
.fingerprint{color:var(--ink3);font-size:12px;font-variant-numeric:tabular-nums;
  border-top:1px solid var(--line);padding-top:10px;margin-top:14px}

.sectionhead{margin:34px 0 14px;padding:12px 14px;border-radius:9px;
  background:var(--panel2);border:1px solid var(--line);
  border-left:3px solid var(--tool)}
.sectionhead h2{font-size:15px;margin:0 0 4px;font-weight:660}
.sectionhead p{margin:0;color:var(--ink3);font-size:12.5px}

.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:0;margin-bottom:12px;overflow:hidden}
.card > .hd{padding:11px 15px;border-bottom:1px solid var(--line);
  display:flex;align-items:baseline;gap:10px;background:var(--panel2)}
.card .stage{font-size:11px;font-weight:700;letter-spacing:.07em;
  text-transform:uppercase;color:var(--ink3);white-space:nowrap}
.card.tool .stage{color:var(--tool)}
.card .ttl{font-weight:650;font-size:14.5px}
.rows{display:flex;flex-direction:column}
.r{display:grid;grid-template-columns:104px minmax(0,1fr);gap:14px;
  padding:10px 15px;border-bottom:1px dashed var(--line)}
.r:last-child{border-bottom:0}
.r .k{font-size:10.5px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;padding-top:3px}
.r.hyp .k{color:var(--hyp)} .r.chg .k{color:var(--chg)}
.r.res .k{color:var(--res)} .r.evi .k{color:var(--evi)}
.r .v{color:var(--ink2);min-width:0}
.r.res .v{color:var(--ink)}
.r .v code{background:var(--panel2);border:1px solid var(--line);
  border-radius:4px;padding:1px 5px;font-size:12.5px}

table{border-collapse:collapse;margin:8px 0 2px;width:100%;
  font-variant-numeric:tabular-nums}
th,td{padding:6px 12px;text-align:right;border-bottom:1px solid var(--line);
  font-size:13px}
th:first-child,td:first-child{text-align:left}
thead th{font-size:10px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink3)}
tbody tr:last-child td{border-bottom:0}
strong{color:var(--ink)}
"""


def md_inline(s: str) -> str:
    """Bold, code and arrows. Escaped first, so the source cannot inject."""
    s = html.escape(s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s.replace("-&gt;", "&rarr;")


def render_table(lines: list[str]) -> str:
    """A markdown pipe table. The separator row is dropped, not rendered."""
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")]
            for ln in lines]
    rows = [r for r in rows if not all(set(c) <= set("-: ") for c in r)]
    if not rows:
        return ""
    head, *body = rows
    th = "".join(f"<th>{md_inline(c)}</th>" for c in head)
    tb = "".join("<tr>" + "".join(f"<td>{md_inline(c)}</td>" for c in r)
                 + "</tr>" for r in body)
    return f"<table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table>"


def main() -> int:
    if not SRC.exists():
        raise SystemExit(f"{SRC.name} missing - run `make reproduce` first")
    text = SRC.read_text(encoding="utf-8")
    lines = text.splitlines()

    # --- header: everything before the first stage heading -----------------
    first = next(i for i, ln in enumerate(lines) if ln.startswith("## "))
    fingerprint, lede, para = [], [], []
    for ln in lines[1:first]:
        s = ln.strip()
        if s.startswith(("Run fingerprint", "PYTHONHASHSEED", "frozen clock")):
            fingerprint.append(s)
            continue
        if s:
            para.append(s)                 # markdown wraps mid-sentence;
        elif para:                         # a blank line is the real break
            lede.append(" ".join(para))
            para = []
    if para:
        lede.append(" ".join(para))

    body, i, in_tools = [], first, False
    while i < len(lines):
        ln = lines[i]

        # A divider then a plain heading marks the post-pipeline section.
        if ln.startswith("## ") and not re.match(r"## Stage ", ln):
            title = ln[3:].strip()
            nxt = i + 1
            blurb = []
            while nxt < len(lines) and not lines[nxt].startswith("## "):
                if lines[nxt].strip() and lines[nxt].strip() != "---":
                    blurb.append(lines[nxt].strip())
                nxt += 1
            body.append(
                f'<div class="sectionhead"><h2>{md_inline(title)}</h2>'
                f'<p>{md_inline(" ".join(blurb))}</p></div>')
            in_tools = True
            i = nxt
            continue

        m = re.match(r"## Stage (\S+) - (.+)", ln)
        if not m:
            i += 1
            continue
        stage, title = m.group(1), m.group(2)
        i += 1

        rows, cur, buf, tbl = [], None, [], []

        def flush():
            nonlocal cur, buf, tbl
            if cur is None:
                return
            inner = ""
            if buf:
                inner += "<div>" + md_inline(" ".join(buf)) + "</div>"
            if tbl:
                inner += render_table(tbl)
            cls = {"Hypothesis": "hyp", "Change": "chg",
                   "Result": "res", "Evidence": "evi"}[cur]
            rows.append(f'<div class="r {cls}"><div class="k">{cur}</div>'
                        f'<div class="v">{inner}</div></div>')
            cur, buf, tbl = None, [], []

        while i < len(lines) and not lines[i].startswith("## "):
            s = lines[i].strip()
            fm = re.match(r"\*\*(" + "|".join(FIELDS) + r")\.\*\*\s*(.*)", s)
            if fm:
                flush()
                cur = fm.group(1)
                if fm.group(2):
                    buf.append(fm.group(2))
            elif s.startswith("|"):
                tbl.append(s)
            elif s:
                buf.append(s)
            i += 1
        flush()

        body.append(
            f'<div class="card{" tool" if in_tools else ""}">'
            f'<div class="hd"><span class="stage">Stage {html.escape(stage)}'
            f'</span><span class="ttl">{md_inline(title)}</span></div>'
            f'<div class="rows">{"".join(rows)}</div></div>')

    page = f"""<!doctype html>
<meta charset="utf-8">
<title>GLOF Risk Tool - improvement changelog</title>
<style>{CSS}</style>
<div class="wrap">
  <h1>Improvement changelog</h1>
  {"".join(f'<p class="lede">{md_inline(p)}</p>' for p in lede)}
  <div class="fingerprint">{md_inline(" ".join(fingerprint))}</div>
  {"".join(body)}
</div>
"""
    SITE.mkdir(parents=True, exist_ok=True)
    dest = SITE / "changelog.html"
    dest.write_text(page, encoding="utf-8", newline="\n")
    n = page.count('class="card')
    print(f"wrote {dest.relative_to(REPO_ROOT).as_posix()} "
          f"({dest.stat().st_size:,} bytes, {n} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
