"""Stage 14: naive single-prompt baseline vs. the multi-agent pipeline.

The baseline is what a competent single-pass summariser does with the same
documents: read them, take each figure at face value, write fluent prose. It is
NOT a strawman - it extracts the same numbers from the same sources using the
same extractor. The only thing it lacks is the reconciliation step, and that is
precisely the variable under test.

Where the two differ:

  baseline   takes the FIRST value it encounters for each quantity, states it
             without qualification, and does not cite. This is the failure the
             project argues against, reproduced faithfully rather than
             caricatured: it produces a confident, readable, unattributed
             sitrep that silently picks 55 or 178 fatalities depending on
             document order.
  advanced   surfaces the disagreement, cites every figure, and refuses to
             adopt a single value.

Scenarios are the 4 real events plus synthetic perturbations that inject
contradictions and fabricated facts, so the harness measures generalisation
rather than performance on the two cases everyone already knows about.

Metrics, all five from the plan:
  citation precision / recall / F1   are cited figures actually in the source,
                                     and are sourced figures actually cited
  contradiction-detection F1         vs. the hand-labelled key
  numeric accuracy                   fraction of stated figures traceable to a source
  human-edit-distance                word-level Levenshtein to the approved text
  hallucination rate                 unsupported claims per report
"""
from __future__ import annotations

import re

from src.reporter.critic import CITATION, NUMBER, _numbers_in

try:
    from Levenshtein import distance as _lev
except ImportError:  # pragma: no cover
    _lev = None


def naive_baseline_draft(retrieved: dict, recon: dict) -> dict:
    """A single-pass summariser: first value wins, no citations, no hedges."""
    seen: dict[str, float] = {}
    order: list[str] = []
    for cl in recon["claims"]:
        q = cl["quantity"]
        if q not in seen:
            seen[q] = cl["normalised_value"]
            order.append(q)

    lines = [f"{retrieved['title']}."]
    for q in order:
        v = seen[q]
        label = q.replace("_", " ")
        vs = f"{v:,.0f}" if abs(v - round(v)) < 1e-6 else f"{v:,.3g}"
        lines.append(f"There were {vs} {label}.")
    lines.append("The situation remains under assessment.")
    return {"event_id": retrieved["event_id"], "model": "naive_single_prompt",
            "sections": {"body": lines},
            "text": " ".join(lines)}


def advanced_text(draft: dict) -> str:
    return " ".join(t for sec in draft["sections"].values() for t in sec)


def citation_metrics(text: str, passages_by_doc: dict[str, list[str]]) -> dict:
    """Are cited figures real, and are real figures cited?"""
    sentences = [s.strip() for s in re.split(r"(?<=[.।])\s+", text) if s.strip()]
    cited_ok = cited_total = 0
    uncited_figures = 0
    for s in sentences:
        nums = _numbers_in(CITATION.sub("", s))
        docs = [d.strip() for c in CITATION.findall(s)
                for d in c.split(";") if d.strip()]
        if not nums:
            continue
        if not docs:
            uncited_figures += len(nums)
            continue
        corpus = " ".join(t for d in docs for t in passages_by_doc.get(d, []))
        corpus_nums = _numbers_in(corpus)
        for n in nums:
            cited_total += 1
            if n in corpus_nums:
                cited_ok += 1
    total_figures = cited_total + uncited_figures
    precision = cited_ok / max(cited_total, 1)
    recall = cited_ok / max(total_figures, 1)
    return {"citation_precision": round(precision, 4),
            "citation_recall": round(recall, 4),
            "citation_f1": round(2 * precision * recall / max(precision + recall, 1e-9), 4),
            "figures_cited": cited_total, "figures_uncited": uncited_figures,
            "figures_supported": cited_ok}


# Sentences that describe the REPORT rather than the event. Their numbers are
# document counts, publisher counts and the as-of date - none of them claims
# about the world, so counting them as unsupported measures the wrong thing.
_META_SENTENCE = re.compile(
    "(?:as of|information in this report|sources:|research prototype|"
    "drawn from|pinned source set|key figures are contested|"
    "यो प्रतिवेदन|स्रोतहरू|सम्म:)", re.IGNORECASE)


def _claim_text(text: str) -> str:
    """Drop report-metadata sentences before measuring numeric fidelity.

    Added after inspecting what the first version flagged: on the Thame draft,
    8 of the 10 "unsupported" figures were the as-of date, the event date, a
    document count, and years inside source identifiers in the Sources line.
    Scoring those as hallucinated casualty figures made the advanced pipeline
    look WORSE than the baseline (0.444 vs 0.367) purely because it cites its
    sources and dates its output, which is backwards.
    """
    parts = re.split(r"(?<=[.।])\s+", text)
    return " ".join(p for p in parts if not _META_SENTENCE.search(p))


def _matches_source(value: float, source_nums: set[float]) -> bool:
    """Exact, or equal after a unit-scale change.

    The draft reports lake area in km2 while sources state m2, so 0.0439 must
    match 43902 - a real correspondence that string comparison misses.
    """
    for c in source_nums:
        if c == value:
            return True
        if c and abs(value - c) <= max(abs(value), abs(c)) * 1e-4:
            return True
        for f in (1e3, 1e6, 1e9):
            if c and (abs(value * f - c) <= abs(c) * 1e-3
                      or abs(c * f - value) <= abs(value) * 1e-3):
                return True
    return False


def numeric_accuracy(text: str, recon: dict) -> dict:
    """Fraction of stated figures that match some value in the sources."""
    source_nums = {float(c["normalised_value"]) for c in recon["claims"]}
    source_nums |= {float(c["value"]) for c in recon["claims"]}
    stated = _numbers_in(CITATION.sub("", _claim_text(text)))
    ok = sum(1 for n in stated if _matches_source(float(n), source_nums))
    return {"numeric_accuracy": round(ok / max(len(stated), 1), 4),
            "figures_stated": len(stated), "figures_traceable": ok}


def hallucination_rate(text: str, recon: dict) -> dict:
    """Unsupported figures per report."""
    na = numeric_accuracy(text, recon)
    unsupported = na["figures_stated"] - na["figures_traceable"]
    return {"unsupported_claims": unsupported,
            "hallucination_rate": round(unsupported / max(na["figures_stated"], 1), 4)}


def contradiction_reflected(text: str, recon: dict) -> dict:
    """Does the text actually surface the disagreements that exist?"""
    total = len(recon["contradictions"])
    if total == 0:
        return {"contradictions_present": 0, "contradictions_reflected": 0,
                "contradiction_recall": 1.0}
    reflected = 0
    low = text.lower()
    for c in recon["contradictions"]:
        vals = [c.get("min"), c.get("max"), c.get("stated_total"), c.get("itemised_sum")]
        vals = [v for v in vals if v is not None]
        # Reflected means BOTH ends of the range appear, or the text explicitly
        # marks the quantity as contested. Stating one endpoint is exactly what
        # the baseline does and must not count.
        shown = sum(1 for v in vals if f"{v:,.0f}" in text or f"{v:g}" in text)
        hedged = any(h in low for h in ("between", "contested", "sources report",
                                        "no single value", "देखि", "मतभेद"))
        if shown >= 2 and hedged:
            reflected += 1
    return {"contradictions_present": total, "contradictions_reflected": reflected,
            "contradiction_recall": round(reflected / total, 4)}


def edit_distance_to_approved(text: str, approved: str) -> dict:
    """Word-level Levenshtein, as the time-saved proxy."""
    a, b = text.split(), approved.split()
    if _lev is None:
        return {"word_edit_distance": None, "normalised": None,
                "note": "Levenshtein unavailable"}
    # Map words to characters so the library's string distance operates on
    # tokens rather than letters.
    vocab = {w: chr(i % 0x10000) for i, w in enumerate(sorted(set(a) | set(b)))}
    d = _lev("".join(vocab[w] for w in a), "".join(vocab[w] for w in b))
    return {"word_edit_distance": d,
            "normalised": round(d / max(len(b), 1), 4),
            "interpretation": ("words a human must change to reach the approved "
                               "text; lower means less rework")}


def perturb(recon: dict, kind: str, seed_idx: int) -> dict:
    """Synthetic scenario: inject a contradiction or a fabricated figure."""
    import copy
    r = copy.deepcopy(recon)
    if kind == "injected_contradiction" and r["claims"]:
        base = r["claims"][seed_idx % len(r["claims"])]
        fake = dict(base)
        fake["normalised_value"] = base["normalised_value"] * 2.7
        fake["value"] = fake["normalised_value"]
        fake["doc_id"] = base["doc_id"] + "__perturbed"
        fake["publisher"] = base["publisher"] + " (perturbed copy)"
        r["claims"].append(fake)
        r["_injected"] = {"kind": kind, "quantity": base["quantity"],
                          "original": base["normalised_value"],
                          "injected": fake["normalised_value"]}
    elif kind == "fabricated_figure":
        r["_injected"] = {"kind": kind, "value": 9412.0,
                          "note": "a figure present in no source"}
    return r
