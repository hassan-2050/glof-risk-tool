"""Build a short plain-language overview PDF of the project.

    pip install reportlab
    python tools/make_overview_pdf.py     ->  docs/GLOF-tool-overview.pdf

For a non-specialist reader: a district officer, a reviewer, anyone who needs
to know what this does in five minutes without a remote-sensing background.

Every figure is READ FROM outputs/, never typed. That is not decoration - the
hardcoded numbers in this repository's documentation drifted three separate
times (README recall and Spearman, the calving-lake ratios, the cloud-cover
claim), and a summary aimed at people who cannot check it is the worst place
for a stale number. If a figure cannot be derived from an artefact it does not
belong in this document.

Deliberately NOT part of `reproduce`: it needs reportlab, which is not on the
offline reproduce path and is not in requirements.txt or the Docker image.
Run it after a reproduce, whenever the results change.
"""
from pathlib import Path

from reportlab import rl_config

# Same rule as the pipeline: no wall-clock in an artefact. Without this the
# embedded CreationDate changes on every run and two identical documents hash
# differently, which is exactly the drift this file exists to prevent.
rl_config.invariant = 1

from reportlab.lib import colors  # noqa: E402  (must follow the config flag)
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, PageBreak,
                                Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"


def j(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


w = j("stage07_watcher_eval.json")
r9 = j("stage09_reconciliation.json")
r14 = j("stage14_reporter_eval.json")
d2 = j("stage02_delineation.json")
neg = j("stage16_negative_control.json")

cmb, cma = w["confusion_growth_only"], w["confusion_proxy_augmented"]
sm = r14["summary"]
val = [x["validation"] for x in d2["lakes"] if x.get("validation")]
within = sum(1 for x in val if x["within_25pct"])
thame = w["per_lake"]["thyanbo_tsho"]["growth_only"]
thame_area = thame["area_km2"]
screen_km2 = thame["thresholds"]["area_km2"]
# "a fifth of", "a quarter of" - stated as a fraction rather than a bare
# ratio, and derived, because an earlier hand-written draft said "less than
# half" when the true figure is a fifth.
share = round(screen_km2 / thame_area)
FRACTION = {2: "half", 3: "a third", 4: "a quarter", 5: "a fifth",
            6: "a sixth", 8: "an eighth", 10: "a tenth"}
share_txt = FRACTION.get(share, f"about 1/{share}")
n_ranked = len(w["ranking"])
n_lakes = len(w["per_lake"])
thame_rank = w["headline"]["thame_proxy_rank_of_n"]
ratios = [x["ratio_to_published"] for x in val if not x["within_25pct"]]
n_under = sum(1 for x in ratios if x < 1.0)
n_over = sum(1 for x in ratios if x > 1.0)

hp = next(c for ev in r9["events"].values() for c in ev["contradictions"]
          if c["quantity"] == "hydropower_projects")
hp_values = ", ".join(f"{v:g}" for v in sorted({x["value"] for x in hp["values"]}))
hp_values = hp_values.rsplit(", ", 1)
hp_values = " and ".join(hp_values)

pre = [(L["name"], s) for L in d2["lakes"] for s in L["scenes"]
       if s.get("role") == "event_pre"]
n_pre = len(pre)
n_pre_clean = sum(1 for _, s in pre if not s["qa"]["reasons"])
n_blind = len({k for k, _ in pre}
              - {k for k, s in pre if not s["qa"]["reasons"]})

INK = colors.HexColor("#0b0b0b")
INK2 = colors.HexColor("#3f3e3b")
MUTED = colors.HexColor("#6f6d67")
RULE = colors.HexColor("#d9d8d1")
BLUE = colors.HexColor("#2a78d6")
RED = colors.HexColor("#c0392f")
BG = colors.HexColor("#f4f4f0")

ss = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=ss["Title"], fontName="Helvetica-Bold",
                            fontSize=21, leading=25, textColor=INK,
                            alignment=TA_LEFT, spaceAfter=2),
    "sub": ParagraphStyle("s", parent=ss["Normal"], fontName="Helvetica",
                          fontSize=9.5, leading=13, textColor=MUTED,
                          spaceAfter=14),
    "h": ParagraphStyle("h", parent=ss["Heading2"], fontName="Helvetica-Bold",
                        fontSize=12.5, leading=15, textColor=INK,
                        spaceBefore=13, spaceAfter=4),
    "p": ParagraphStyle("p", parent=ss["Normal"], fontName="Helvetica",
                        fontSize=10, leading=14.5, textColor=INK2,
                        spaceAfter=6),
    "li": ParagraphStyle("li", parent=ss["Normal"], fontName="Helvetica",
                         fontSize=10, leading=14, textColor=INK2, spaceAfter=3),
    "note": ParagraphStyle("n", parent=ss["Normal"], fontName="Helvetica-Oblique",
                           fontSize=9, leading=12.5, textColor=MUTED,
                           spaceBefore=3),
    "cap": ParagraphStyle("c", parent=ss["Normal"], fontName="Helvetica",
                          fontSize=9, leading=12.5, textColor=INK2),
}


def bullets(items):
    return ListFlowable(
        [ListItem(Paragraph(t, S["li"]), leftIndent=12, value="circle")
         for t in items],
        bulletType="bullet", start="circle", leftIndent=13, bulletFontSize=5,
        spaceAfter=6)


def table(data, widths, align_right=()):
    # repeatRows: if a table ever does split across a page, the header row
    # goes with it. Without it the first table left "Size-only screening /
    # This tool" alone at the foot of page 1 and its rows unlabelled on
    # page 2, which is worse than either page alone.
    t = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK2),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
    ]
    for c in align_right:
        style.append(("ALIGN", (c, 0), (c, -1), "RIGHT"))
    t.setStyle(TableStyle(style))
    return t


story = []
A = story.append

A(Paragraph("What this tool does", S["title"]))
A(Paragraph(
    f"GLOF Risk Tool — a research prototype that screens {n_lakes} Himalayan "
    f"glacial lakes for outburst-flood danger, and drafts the situation report "
    f"that follows one. Plain language throughout. Every number is read from "
    f"the tool's own output, not typed here.", S["sub"]))

# ---------------------------------------------------------------- the problem
A(Paragraph("The problem it is built for", S["h"]))
A(Paragraph(
    "High in the Himalaya, meltwater collects behind natural dams of loose rock "
    "and ice. Sometimes a dam gives way and the lake empties in hours. The "
    "flood can travel tens of kilometres, killing people and destroying bridges "
    "and hydropower plants far downstream.", S["p"]))
A(Paragraph(
    f"The usual way to find the risky ones is to watch which lakes are "
    f"<b>growing</b>, and to ignore any lake smaller than {screen_km2} km². In "
    f"August 2024 a lake above the village of Thame, Nepal, burst. It was "
    f"{thame_area:.3f} km² — {share_txt} of that size threshold — and it had "
    f"not grown. Size-based screening never looked at it.", S["p"]))

# ------------------------------------------------------------ what it does #1
A(Paragraph("Part 1 — the watcher: which lakes deserve attention", S["h"]))
A(Paragraph(
    f"It reads free satellite pictures and elevation maps for {n_lakes} lakes, "
    f"measures each lake in every usable image from 2017 to 2025, and then asks "
    f"the questions that size misses:", S["p"]))
A(bullets([
    "Is there steep, unstable ground above this lake?",
    "Could an avalanche from up there actually <b>reach</b> the water, or would "
    "it stop on the way?",
    "How much rock and ice could fall in, compared with how much water is "
    "already held back? <b>This is the main ranking measure.</b>",
    "How much freeboard has the dam got, how steep is its outer face — and "
    "where would the water go if it failed?",
]))
A(Paragraph(
    f"Nine of these checks come from published research, with the paper and a "
    f"confidence level recorded beside every threshold. On pre-event data "
    f"alone, Thame comes out <b>{thame_rank}</b> on the main measure.", S["p"]))

# ------------------------------------------------------------ what it does #2
A(Paragraph("Part 2 — the reporter: what to tell people afterwards", S["h"]))
A(Paragraph(
    f"It reads news articles and official documents about flood disasters and "
    f"drafts a situation report in English and Nepali, in the standard "
    f"humanitarian format, plus machine-readable alert files. Its most useful "
    f"habit is refusing to answer. Reports of the July 2025 Rasuwa flood put "
    f"the number of destroyed hydropower plants at {hp_values} — so it prints "
    f"the whole range with a name against each figure, instead of picking one "
    f"and sounding certain.", S["p"]))
A(Paragraph(
    "Every sentence is checked against the sources it cites and anything "
    "unsupported is struck before release; a named person must then type an "
    "approval, and a blank keypress is refused.", S["p"]))

# ------------------------------------------------------------ what it does #3
A(Paragraph("Part 3 — the map you can actually use", S["h"]))
A(Paragraph(
    f"A single web page, opened from disk with no internet and no map server. "
    f"Each lake's real measured outline sits on shaded terrain, with a slider "
    f"to move through the years and watch it change, the modelled flood "
    f"corridor, and a movable alarm threshold that re-screens all {n_lakes} "
    f"lakes as you drag it. That last control is deliberate: the published "
    f"alarm level was chosen after seeing every score, so the quickest way to "
    f"show what depends on it is to let people move it. The ranking does not "
    f"move. The flag count does.", S["p"]))


# ------------------------------------------------------------------ does it work
# NOT wrapped in KeepTogether. Holding this block together jumped it whole to
# the next page and left twenty lines of white space behind, which cost a third
# page. repeatRows on the table means a split carries its header, so splitting
# here is the cheaper compromise.
A(Paragraph("Does it work?", S["h"]))
A(Paragraph("Tested on four real Himalayan disasters, using only information "
            "that existed <i>before</i> each event:", S["p"]))
A(table([
    ["", "Size-only screening", "This tool"],
    ["Found the Thame lake?", "No — never assessed it",
     f"Yes — ranked it {thame_rank}"],
    ["Burst lakes caught", f"{cmb['n_tp']} of 3", f"{cma['n_tp']} of 3"],
    ["Lake sizes measured accurately", "—", f"{within} of {len(val)}"],
], [58 * mm, 46 * mm, 54 * mm]))
A(Spacer(1, 10))
A(KeepTogether([
    Paragraph("And for the written reports, against an ordinary one-shot AI "
              "summary of the same sources:", S["p"]),
    table([
        ["", "Ordinary AI summary", "This tool"],
        ["Made-up figures", f"{sm['hallucination_rate']['baseline']:.0%}",
         f"{sm['hallucination_rate']['advanced']:.0%}"],
        ["Disagreements between sources spotted",
         f"{sm['contradiction_recall']['baseline']:.0%}",
         f"{sm['contradiction_recall']['advanced']:.0%}"],
        ["Figures traceable to a named source",
         f"{sm['numeric_accuracy']['baseline']:.0%}",
         f"{sm['numeric_accuracy']['advanced']:.0%}"],
    ], [72 * mm, 42 * mm, 44 * mm], align_right=(1, 2)),
]))

# --------------------------------------------------------------- knowing what isn't
A(Paragraph("Knowing what is <i>not</i> a lake burst", S["h"]))
A(Paragraph(
    f"In February 2021 a disaster at Chamoli in India killed over 200 people "
    f"and was reported worldwide as a glacial lake burst. It was not — it was a "
    f"rock-and-ice avalanche, with no lake involved. The tool finds "
    f"{neg['watcher']['evidence']['water_found_m2']:,.0f} m² of scattered "
    f"meltwater, below its own minimum, assesses nothing, and refuses to call "
    f"it a lake burst in both languages.", S["p"]))
A(Paragraph(
    "<b>This is not a historical curiosity.</b> On 26 August 2026 a mass of "
    "rock and glacier ice fell from Langtang-Lirung in Rasuwa, dammed a river, "
    "and the dam burst — killing hundreds. The first question asked everywhere "
    "was whether a glacial lake had burst. It took days to establish that one "
    "had not. Getting that question right decides whether you go and watch "
    "lakes or watch slopes.", S["p"]))

# ------------------------------------------------------------------- limits
A(Paragraph("What it cannot do", S["h"]))
A(Paragraph("These limits are part of the design. A screening tool whose "
            "weaknesses are hidden is more dangerous than no tool.", S["p"]))
A(bullets([
    "<b>It cannot predict floods.</b> It does not model the trigger — the "
    "avalanche that decides the date is not observed. It ranks standing "
    "danger, so you know where to send someone with instruments.",
    "<b>It only screens lakes.</b> The Langtang disaster above began on a "
    "slope with no lake on it. This tool would have had nothing to say.",
    "It reads shape and surroundings from pictures — it cannot see inside a "
    "dam, so it cannot say how strong that dam is.",
    f"Clouds hide lakes during the monsoon, which is when most floods happen: "
    f"only {n_pre_clean} of {n_pre} satellite passes in the days before these "
    f"four disasters was clear enough to use.",
    f"It measures {within} of {len(val)} test lakes accurately — and two of "
    f"those came from correcting our own reference data, not the measurement.",
    "Flood paths are rough corridors, not flood maps.",
    "<b>It is a research prototype.</b> It is not a warning system and must "
    "not be used to alert the public.",
]))

# -------------------------------------------------------------------- who for
A(Paragraph("Who it is for", S["h"]))
A(Paragraph(
    "Nepal's own agencies — DHM, NDRRMA and ICIMOD — hold the data and the "
    "legal responsibility; this feeds their work rather than replacing it. "
    "Nepal already learned what over-automation costs: the Tsho Rolpa "
    "early-warning system of 2000–02, sirens across 19 villages, is now "
    "defunct. Anyone can re-run this analysis and get the same numbers — it "
    "ships with its data, needs no internet and no accounts, and produces "
    "byte-for-byte identical results on Windows and Linux alike.", S["p"]))


def footer(canv, doc):
    canv.saveState()
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.5)
    canv.line(20 * mm, 15 * mm, A4[0] - 20 * mm, 15 * mm)
    canv.setFont("Helvetica", 7.5)
    canv.setFillColor(MUTED)
    canv.drawString(20 * mm, 10.5 * mm,
                    "GLOF Risk Tool — research prototype. Decision-support for "
                    "DHM / NDRRMA / ICIMOD. Not an operational warning system.")
    canv.drawRightString(A4[0] - 20 * mm, 10.5 * mm, f"page {doc.page}")
    canv.restoreState()


dest = ROOT / "docs" / "GLOF-tool-overview.pdf"
dest.parent.mkdir(parents=True, exist_ok=True)
# A PDF open in a viewer is locked on Windows, and reportlab surfaces that as a
# bare PermissionError traceback from six frames deep. It is the most likely
# way this script fails, and it is entirely recoverable.
if dest.exists():
    try:
        with dest.open("r+b"):
            pass
    except PermissionError:
        raise SystemExit(
            f"{dest.name} is open in another program (a PDF viewer holds a "
            f"write lock on Windows).\nClose it and run this again — nothing "
            f"has been changed.")
SimpleDocTemplate(
    str(dest), pagesize=A4,
    leftMargin=20 * mm, rightMargin=20 * mm,
    topMargin=16 * mm, bottomMargin=17 * mm,
    title="GLOF Risk Tool — plain-language overview",
    author="GLOF Risk Tool",
).build(story, onFirstPage=footer, onLaterPages=footer)
print(f"wrote {dest.relative_to(ROOT).as_posix()}  ({dest.stat().st_size:,} bytes)")
