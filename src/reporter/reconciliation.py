"""Stage 9: extract every numeric claim, then surface where sources disagree.

The argument this stage exists to make: for high-stakes reporting, the most
valuable thing an agent can do is refuse to pick a number. Four sources say the
Rasuwa flood damaged 4, 5, 8 or 11 hydropower projects. A fluent summariser
chooses one and reads beautifully. The correct behaviour is to report the
spread and say who claims what.

Two kinds of disagreement are detected, and the second is the one most systems
miss entirely:

  cross_source    two documents give different values for the same quantity
  intra_document  ONE document contradicts itself. NDRRMA's Rasuwa report
                  states 23 human casualties and then itemises 19 dead, 13
                  missing and 1 injured, which sum to 33. An agent that only
                  compares figures BETWEEN documents cannot see this.

Extraction is rule-based rather than model-based, on purpose. The figures we
need are dense, well-formed and unit-bearing, so a grammar handles them
exactly; and a deterministic extractor means the contradiction table is
reproducible and auditable, which is the whole claim being made. An LLM would
add a nondeterministic step to the one part of the pipeline whose value is that
you can check it.
"""
from __future__ import annotations

import re

# Scale words that multiply a bare number.
SCALES = {
    "thousand": 1e3, "million": 1e6, "billion": 1e9,
    "lakh": 1e5, "crore": 1e7,
}

# Quantity vocabulary. Order matters: the first match wins, so specific
# phrases must precede generic ones.
QUANTITY_PATTERNS: list[tuple[str, str]] = [
    ("hydropower_projects", r"hydro(?:power|\s*projects?|\s*electric)|HEP\b"),
    ("hydropower_mw", r"\bMW\b|megawatt"),
    ("deaths", r"\bdeaths?\b|\bkilled\b|\bfatalit"),
    ("missing", r"\bmissing\b"),
    ("injured", r"\binjured\b"),
    ("casualties_total", r"human casualt|casualt"),
    ("displaced", r"displac"),
    ("homes_destroyed", r"homes? destroyed|houses? destroyed"),
    ("volume_m3", r"cubic metres?|cubic meters?|\bm3\b|m³"),
    ("area_km2", r"square kilometres?|sq\.?\s*km|km2|km²"),
    ("area_m2", r"square metres?|square meters?|\bm2\b|m²"),
    ("distance_km", r"\bkm\b downstream|kilometres? downstream|\bkm\b"),
    ("height_m", r"\bmetres? high\b|\bm high\b|\bmetre-high\b"),
    ("elevation_m", r"\bmetres?\b|\bm\b"),
    ("percent", r"per cent|percent|%"),
]

# Numbers that are parts of DATES, not quantities. Without this guard "surface
# water collected ... by July 7" and "drained ... by July 8" were extracted as
# lake AREAS, because "sq. km" sits a few words away, and the Rasuwa sitrep
# reported lake area as "between 7e-06 and 8 square kilometres". Dates are
# dense in situation reports and every one of them is a false figure.
DATE_CONTEXT = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s*$|^\s*(?:st|nd|rd|th)?\s*(?:January|February|March|"
    r"April|May|June|July|August|September|October|November|December)|"
    r"^\s*[-/]\s*\d|\d\s*[-/]\s*$",
    re.IGNORECASE)

# Four-digit years are never a quantity we care about here.
YEAR = re.compile(r"^(19|20)\d{2}$")

NUMBER = re.compile(
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<scale>thousand|million|billion|lakh|crore))?",
    re.IGNORECASE)


def _classify_quantity(context: str, num_start: int, num_end: int) -> str | None:
    """The quantity whose keyword sits NEAREST the number.

    First-match-in-list-order looked reasonable and was badly wrong, because
    these sentences carry several quantities at once. "damaged structures
    associated with 11 hydropower projects totalling 405 MW" made 405 a project
    COUNT, so the reported range became 4 to 405. Worse, Zhang's "178
    fatalities and destroyed three downstream hydropower projects" classified
    the headline death toll as hydropower and dropped it out of the fatality
    contradiction entirely - the single most important disagreement in the
    project, lost to a list ordering.

    Proximity is the right rule: in "11 hydropower projects totalling 405 MW",
    MW is two characters from 405 and "hydropower" is twenty, so each number
    binds to the unit it actually belongs to.
    """
    best = None
    for name, pattern in QUANTITY_PATTERNS:
        for m in re.finditer(pattern, context, re.IGNORECASE):
            # Distance from the number to this keyword, zero if it overlaps.
            if m.end() <= num_start:
                d = num_start - m.end()
            elif m.start() >= num_end:
                d = m.start() - num_end
            else:
                d = 0
            if best is None or d < best[0]:
                best = (d, name)
    return best[1] if best else None


def extract_claims(passage: dict) -> list[dict]:
    """Every numeric claim in one passage, with its source attached."""
    text = passage["text"]
    claims = []
    for m in NUMBER.finditer(text):
        raw = m.group("num")
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        scale = m.group("scale")
        if scale:
            value *= SCALES[scale.lower()]

        if YEAR.match(raw.replace(",", "")):
            continue
        # Drop date components: "July 7", "7 July", "2024-08-16".
        before = text[max(0, m.start() - 12):m.start()]
        after = text[m.end():m.end() + 12]
        if DATE_CONTEXT.search(before) or DATE_CONTEXT.search(after):
            continue

        # A window either side is enough: these are single-clause factual
        # statements, not prose where the referent drifts.
        lo, hi = max(0, m.start() - 60), min(len(text), m.end() + 60)
        context = text[lo:hi]
        quantity = _classify_quantity(context, m.start() - lo, m.end() - lo)
        if quantity is None:
            continue

        # Normalise areas so km2 and m2 claims about the same lake compare.
        norm_value, norm_unit = value, quantity
        if quantity == "area_m2":
            norm_value, norm_unit = value / 1e6, "area_km2"

        claims.append({
            "value": value,
            "normalised_value": norm_value,
            "quantity": norm_unit,
            "raw": m.group(0).strip(),
            "context": context.strip(),
            "passage_id": passage["passage_id"],
            "doc_id": passage["doc_id"],
            "publisher": passage["source"]["publisher"],
            "doc_type": passage["source"]["doc_type"],
            "published": passage["source"]["published"],
            "kind": passage["kind"],
        })
    return claims


def _disagree(a: float, b: float, rtol: float) -> bool:
    if a == b:
        return False
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom > rtol


def find_contradictions(claims: list[dict], cfg) -> list[dict]:
    """Group claims by quantity and report where sources disagree."""
    rtol = cfg.require("reporter.numeric_reconciliation.relative_tolerance")
    by_quantity: dict[str, list[dict]] = {}
    for c in claims:
        by_quantity.setdefault(c["quantity"], []).append(c)

    out = []
    for quantity, group in sorted(by_quantity.items()):
        values = [g["normalised_value"] for g in group]
        if len(group) < 2:
            continue
        lo, hi = min(values), max(values)
        if not _disagree(lo, hi, rtol):
            continue

        docs = {g["doc_id"] for g in group}
        kind = "cross_source" if len(docs) > 1 else "intra_document"
        # Severity from the size of the spread. A doubling is a different kind
        # of problem from a rounding difference, and a sitrep should not treat
        # them alike.
        spread = (hi - lo) / max(abs(lo), 1e-9)
        severity = "high" if spread >= 0.5 else "medium" if spread >= 0.1 else "low"

        out.append({
            "quantity": quantity,
            "kind": kind,
            "severity": severity,
            "min": lo, "max": hi,
            "spread_ratio": round(hi / max(lo, 1e-9), 3),
            "n_claims": len(group),
            "n_documents": len(docs),
            "values": sorted(
                ({"value": g["normalised_value"], "publisher": g["publisher"],
                  "doc_id": g["doc_id"], "passage_id": g["passage_id"],
                  "doc_type": g["doc_type"], "published": g["published"],
                  "context": g["context"]} for g in group),
                key=lambda v: v["value"]),
            # The sentence a drafting agent should use. Never an average:
            # averaging two casualty counts invents a number no source reported.
            "reportable_sentence": (
                f"Sources report between {lo:g} and {hi:g} for {quantity.replace('_', ' ')}"
                f" ({', '.join(sorted({g['publisher'].split(' (')[0] for g in group}))})."),
        })
    return out


def check_internal_arithmetic(claims: list[dict], cfg) -> list[dict]:
    """Does a document's stated total match its own itemised parts?

    Separate from the value-comparison path because the failure is different:
    the numbers do not disagree with each other, they disagree with their own
    sum. NDRRMA states 23 casualties then itemises 19 + 13 + 1 = 33.
    """
    rtol = cfg.require("reporter.numeric_reconciliation.relative_tolerance")
    findings = []
    by_doc: dict[str, list[dict]] = {}
    for c in claims:
        by_doc.setdefault(c["doc_id"], []).append(c)

    for doc_id, group in sorted(by_doc.items()):
        totals = [g for g in group if g["quantity"] == "casualties_total"]
        parts = {q: [g for g in group if g["quantity"] == q]
                 for q in ("deaths", "missing", "injured")}
        if not totals or not any(parts.values()):
            continue
        part_sum = sum(max((g["normalised_value"] for g in v), default=0.0)
                       for v in parts.values())
        for t in totals:
            if part_sum > 0 and _disagree(t["normalised_value"], part_sum, rtol):
                findings.append({
                    "quantity": "casualties_total",
                    "kind": "intra_document",
                    "severity": "high",
                    "doc_id": doc_id,
                    "publisher": t["publisher"],
                    "stated_total": t["normalised_value"],
                    "itemised_sum": part_sum,
                    "components": {q: [g["normalised_value"] for g in v]
                                   for q, v in parts.items() if v},
                    "passage_id": t["passage_id"],
                    "reportable_sentence": (
                        f"{t['publisher'].split(' (')[0]} states a total of "
                        f"{t['normalised_value']:g} casualties but itemises figures "
                        f"summing to {part_sum:g}; the document is internally "
                        f"inconsistent."),
                })
    return findings


def reconcile_event(retrieved: dict, cfg) -> dict:
    claims = []
    for p in retrieved["passages"]:
        claims.extend(extract_claims(p))
    cross = find_contradictions(claims, cfg)
    internal = check_internal_arithmetic(claims, cfg)
    all_c = cross + internal
    return {
        "event_id": retrieved["event_id"],
        "n_claims_extracted": len(claims),
        "n_contradictions": len(all_c),
        "by_severity": {s: sum(1 for c in all_c if c["severity"] == s)
                        for s in ("high", "medium", "low")},
        "contradictions": all_c,
        "claims": claims,
    }
