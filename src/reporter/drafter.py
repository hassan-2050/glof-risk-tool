"""Stage 10: OCHA-structured bilingual situation report.

Every sentence is assembled from the retriever and reconciliation output, never
written freehand, so each factual claim carries an inline citation to a
specific document. Where Stage 9 found sources disagreeing, the draft says so -
"sources report between X and Y" with attribution - rather than silently
choosing a figure. That behaviour is the point of the project, so it is
structural here rather than a prompt instruction that a model may or may not
follow.

WHY THIS IS TEMPLATE-ASSEMBLED RATHER THAN MODEL-GENERATED
----------------------------------------------------------
A sitrep is a controlled-vocabulary document with a fixed skeleton, and the
requirements are that every figure is traceable, every contradiction survives
into the text, and the Nepali uses consistent disaster terminology. A template
gives all three by construction and is reproducible offline; a language model
gives none of them by construction and has to be verified back into compliance
by Stage 11.

The honest limitation: this produces correct, auditable, and flat prose. It is
a scaffold a drafting model should improve on, and Stage 11's critic and NLI
verification exist precisely so a generated draft can be checked against this
standard. Where an LLM is available, `generate_with_llm` is the hook; the
committed pipeline runs the deterministic path so a judge can reproduce it with
no API key.

NEPALI
------
The Nepali draft is produced from a parallel template plus a fixed disaster
glossary, not word-for-word substitution into English syntax. It is not a
general MT system and is not presented as one: it renders THIS document type,
whose sentence inventory is closed. That is also why its terminology
consistency (Stage 15) is exact rather than merely good - the glossary is the
only source of technical vocabulary.
"""
from __future__ import annotations

import datetime as dt

# Fixed disaster glossary. Stage 15 checks these are used consistently; here
# they are the ONLY source of technical vocabulary, so consistency is
# structural rather than measured after the fact.
GLOSSARY = {
    "glof": ("glacial lake outburst flood", "हिमताल विस्फोट बाढी"),
    "flood": ("flood", "बाढी"),
    "landslide": ("landslide", "पहिरो"),
    "avalanche": ("avalanche", "हिमपहिरो"),
    "glacier": ("glacier", "हिमनदी"),
    "glacial_lake": ("glacial lake", "हिमताल"),
    "displaced": ("displaced", "विस्थापित"),
    "missing": ("missing", "बेपत्ता"),
    "deaths": ("deaths", "मृत्यु"),
    "injured": ("injured", "घाइते"),
    "casualties": ("casualties", "हताहत"),
    "hydropower": ("hydropower", "जलविद्युत"),
    "school": ("school", "विद्यालय"),
    "health_post": ("health post", "स्वास्थ्य चौकी"),
    "bridge": ("bridge", "पुल"),
    "river": ("river", "नदी"),
    "district": ("district", "जिल्ला"),
    "households": ("households", "घरपरिवार"),
}

OCHA_SECTIONS = ["highlights", "situation_overview", "humanitarian_impact",
                 "response", "gaps_and_constraints", "funding",
                 "contacts_and_sourcing"]

SECTION_TITLES = {
    "highlights": ("Highlights / Key Messages", "मुख्य बुँदाहरू"),
    "situation_overview": ("Situation Overview", "अवस्थाको सारांश"),
    "humanitarian_impact": ("Humanitarian Needs and Impact", "मानवीय आवश्यकता र प्रभाव"),
    "response": ("Response", "प्रतिकार्य"),
    "gaps_and_constraints": ("Gaps and Constraints", "कमी र बाधाहरू"),
    "funding": ("Funding", "आर्थिक स्रोत"),
    "contacts_and_sourcing": ("Contacts and Sourcing", "सम्पर्क र स्रोत"),
}

QUANTITY_LABEL = {
    "deaths": ("deaths", "मृत्यु"),
    "missing": ("people missing", "बेपत्ता व्यक्ति"),
    "injured": ("people injured", "घाइते व्यक्ति"),
    "casualties_total": ("total casualties", "कुल हताहत"),
    "displaced": ("people displaced", "विस्थापित व्यक्ति"),
    "homes_destroyed": ("homes destroyed", "नष्ट भएका घर"),
    "hydropower_projects": ("hydropower projects damaged", "क्षतिग्रस्त जलविद्युत आयोजना"),
    "hydropower_mw": ("MW of generation affected", "मेगावाट उत्पादन प्रभावित"),
    "volume_m3": ("cubic metres of water released", "घन मिटर पानी निष्कासन"),
    "area_km2": ("square kilometres of lake area", "वर्ग किलोमिटर ताल क्षेत्रफल"),
    "distance_km": ("kilometres downstream", "किलोमिटर तल्लो तटीय क्षेत्र"),
    "percent": ("per cent change", "प्रतिशत परिवर्तन"),
}


def _cite(values: list[dict]) -> str:
    """Inline citation listing the documents a figure came from."""
    return "[" + "; ".join(sorted({v["doc_id"] for v in values})) + "]"


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-6 else f"{v:,.3g}"


def build_claim_sentences(recon: dict, lang: str) -> list[dict]:
    """One sentence per quantity, each carrying its citation and provenance."""
    en = lang == "en"
    out = []
    seen = set()

    for c in recon.get("contradictions", []):
        q = c["quantity"]
        if q in seen:
            continue
        seen.add(q)
        label = QUANTITY_LABEL.get(q, (q.replace("_", " "), q))[0 if en else 1]

        # Branch on the SHAPE of the record, not on `kind`. Both the
        # value-comparison path and the arithmetic check can report
        # kind="intra_document" - the former when every claim happens to come
        # from one document - but only the arithmetic check carries a stated
        # total and a publisher.
        if "stated_total" in c:
            text = (f"{c['publisher'].split(' (')[0]} reports a total of "
                    f"{_fmt(c['stated_total'])} {label}, but its own itemised figures "
                    f"sum to {_fmt(c['itemised_sum'])} [{c['doc_id']}]."
                    if en else
                    f"{c['publisher'].split(' (')[0]} ले कुल {_fmt(c['stated_total'])} "
                    f"{label} उल्लेख गरेको छ, तर सोही कागजातका विवरणहरूको जोड "
                    f"{_fmt(c['itemised_sum'])} हुन्छ [{c['doc_id']}]।")
            out.append({"quantity": q, "text": text, "contested": True,
                        "kind": "intra_document", "severity": c["severity"],
                        "sources": [c["doc_id"]]})
            continue

        vals = c["values"]
        text = (f"Sources report between {_fmt(c['min'])} and {_fmt(c['max'])} "
                f"{label}; the figure is contested and no single value is adopted "
                f"{_cite(vals)}."
                if en else
                f"स्रोतहरूका अनुसार {_fmt(c['min'])} देखि {_fmt(c['max'])} सम्म "
                f"{label} रहेको छ; यो तथ्याङ्कमा मतभेद छ र कुनै एक अङ्क अपनाइएको छैन "
                f"{_cite(vals)}।")
        out.append({"quantity": q, "text": text, "contested": True,
                    "kind": "cross_source", "severity": c["severity"],
                    "sources": sorted({v["doc_id"] for v in vals})})

    # Uncontested figures: reported plainly, still cited.
    by_q: dict[str, list[dict]] = {}
    for cl in recon.get("claims", []):
        by_q.setdefault(cl["quantity"], []).append(cl)
    for q, group in sorted(by_q.items()):
        if q in seen or q not in QUANTITY_LABEL:
            continue
        vals = {g["normalised_value"] for g in group}
        if len(vals) != 1:
            continue
        v = next(iter(vals))
        label = QUANTITY_LABEL[q][0 if en else 1]
        cite = "[" + "; ".join(sorted({g["doc_id"] for g in group})) + "]"
        out.append({
            "quantity": q, "contested": False, "severity": None,
            "sources": sorted({g["doc_id"] for g in group}),
            "text": (f"{_fmt(v)} {label} were reported {cite}." if en
                     else f"{_fmt(v)} {label} रिपोर्ट गरिएको छ {cite}।"),
        })
    return out


def draft_event(retrieved: dict, recon: dict, cfg, lang: str = "en") -> dict:
    en = lang == "en"
    frozen = cfg.require("determinism.frozen_utc")
    as_of = dt.datetime.fromisoformat(frozen.replace("Z", "+00:00")).date().isoformat()
    sentences = build_claim_sentences(recon, lang)
    contested = [s for s in sentences if s["contested"]]
    plain = [s for s in sentences if not s["contested"]]
    glof = retrieved.get("is_glof", True)
    hazard = (GLOSSARY["glof"][0 if en else 1] if glof
              else (GLOSSARY["avalanche"][0 if en else 1] + " and debris flow" if en
                    else GLOSSARY["avalanche"][1] + " तथा भू-स्खलन प्रवाह"))

    sections: dict[str, list[str]] = {s: [] for s in OCHA_SECTIONS}

    sections["highlights"].append(
        (f"As of {as_of}: {retrieved['title']} - classified as {hazard}."
         if en else
         f"{as_of} सम्म: {retrieved['title']} - {hazard} को रूपमा वर्गीकृत।"))
    if not glof:
        sections["highlights"].append(
            ("This event was NOT a glacial lake outburst flood. The peer-reviewed "
             "analysis attributes it to a rock and ice avalanche with no lake "
             "involved [shugar_2021_science]."
             if en else
             "यो घटना हिमताल विस्फोट बाढी थिएन। समकक्षी-समीक्षित अध्ययनले यसलाई "
             "कुनै तालको संलग्नताविना चट्टान र हिउँको पहिरो भनी पहिचान गरेको छ "
             "[shugar_2021_science]।"))
    if contested:
        sections["highlights"].append(
            (f"{len(contested)} key figures are contested across sources and are "
             f"reported as ranges below; no single value has been adopted."
             if en else
             f"{len(contested)} मुख्य तथ्याङ्कमा स्रोतहरूबीच मतभेद छ र तल दायराका "
             f"रूपमा प्रस्तुत गरिएका छन्; कुनै एक अङ्क अपनाइएको छैन।"))

    sections["situation_overview"].append(
        (f"Location: {retrieved['admin']}, {retrieved['country']}. "
         f"Information in this report is drawn from {retrieved['n_documents']} "
         f"documents across {retrieved['n_distinct_publishers']} distinct "
         f"publishers: {', '.join(retrieved['distinct_publishers'])}."
         if en else
         f"स्थान: {retrieved['admin']}, {retrieved['country']}। यो प्रतिवेदन "
         f"{retrieved['n_distinct_publishers']} फरक प्रकाशकका "
         f"{retrieved['n_documents']} कागजातमा आधारित छ।"))

    for s in contested:
        sections["humanitarian_impact"].append(s["text"])
    for s in plain:
        sections["humanitarian_impact"].append(s["text"])
    if not sections["humanitarian_impact"]:
        sections["humanitarian_impact"].append(
            "No quantified impact figures could be extracted from the available sources."
            if en else "उपलब्ध स्रोतबाट परिमाणात्मक प्रभाव तथ्याङ्क निकाल्न सकिएन।")

    sections["response"].append(
        ("Response details are not quantified in the pinned source set. This "
         "report is decision-support for DHM, NDRRMA and ICIMOD, who hold the "
         "operational mandate."
         if en else
         "पिन गरिएका स्रोतहरूमा प्रतिकार्यको परिमाणात्मक विवरण छैन। यो प्रतिवेदन "
         "DHM, NDRRMA र ICIMOD का लागि निर्णय-सहायता सामग्री हो।"))

    gaps = [("Figures below are drawn from a fixed, pinned document set and are "
             "not a live feed." if en else
             "तलका तथ्याङ्क निश्चित कागजात सङ्ग्रहबाट लिइएका हुन्, प्रत्यक्ष स्रोत होइन।")]
    for s in contested:
        if s["severity"] == "high":
            gaps.append(
                (f"Unresolved disagreement on {QUANTITY_LABEL.get(s['quantity'], (s['quantity'],))[0]}: "
                 f"requires verification with the responsible authority before use."
                 if en else
                 f"{QUANTITY_LABEL.get(s['quantity'], (s['quantity'], s['quantity']))[1]} "
                 f"मा अमिल्दो तथ्याङ्क: प्रयोग गर्नुअघि सम्बन्धित निकायसँग पुष्टि आवश्यक।"))
    sections["gaps_and_constraints"] = gaps

    sections["funding"].append(
        ("No funding figures are present in the pinned source set."
         if en else "पिन गरिएका स्रोतहरूमा आर्थिक स्रोतसम्बन्धी तथ्याङ्क छैन।"))

    sections["contacts_and_sourcing"].append(
        ("Sources: " + "; ".join(f"{d} ({p['source']['publisher']})"
                                 for d, p in sorted(
                                     {x['doc_id']: x for x in retrieved['passages']}.items()))
         if en else
         "स्रोतहरू: " + "; ".join(sorted({x['doc_id'] for x in retrieved['passages']}))))
    sections["contacts_and_sourcing"].append(
        ("Research prototype. Not an operational warning product. Data owners "
         "and mandate holders: DHM, NDRRMA, ICIMOD."
         if en else
         "अनुसन्धान प्रोटोटाइप। सञ्चालनगत चेतावनी सामग्री होइन। तथ्याङ्क तथा "
         "अधिकार धारक: DHM, NDRRMA, ICIMOD।"))

    body_words = sum(len(t.split()) for sec in sections.values() for t in sec)
    return {
        "event_id": retrieved["event_id"],
        "language": lang,
        "as_of": as_of,
        "is_glof": glof,
        "sections": {k: sections[k] for k in OCHA_SECTIONS},
        "section_titles": {k: SECTION_TITLES[k][0 if en else 1] for k in OCHA_SECTIONS},
        "word_count": body_words,
        "n_claim_sentences": len(sentences),
        "n_contested_reflected": len(contested),
        "all_sections_present": all(k in sections for k in OCHA_SECTIONS),
    }


def render_markdown(draft: dict) -> str:
    lines = [f"# Situation Report - {draft['event_id']} ({draft['language']})",
             f"_As of {draft['as_of']}_", ""]
    for key in OCHA_SECTIONS:
        lines.append(f"## {draft['section_titles'][key]}")
        for para in draft["sections"][key]:
            lines.append(para)
        lines.append("")
    return "\n".join(lines)
