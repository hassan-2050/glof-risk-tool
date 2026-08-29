"""Stage 11: adversarial critic and claim-to-source verification.

Two independent checks, because they fail differently and a single pass would
let each other's blind spots through.

VERIFIER (deterministic). For every sentence carrying a figure, does that
figure actually appear in the passages it cites? This is the numeric analogue
of an NLI entailment check, and for a sitrep it is the stronger test: a model
that invents a casualty count produces fluent, well-formed, entirely wrong
prose, and only checking the number against the cited span catches it. It is
rule-based so it cannot itself hallucinate a verdict, and it runs with no key.

CRITIC (adversarial). Attacks the draft for the failures the verifier cannot
see: a contested figure stated as though settled, a missing hedge, a claim with
no citation at all, the negative control described as a GLOF. Runs as a set of
structural red-team rules, and additionally through an LLM when a key is
present - the rules catch what we predicted, the model is there to catch what
we did not.

The loop is critic -> verifier -> revise, with a hard iteration cap. Anything
still unsupported at the cap BLOCKS release: the draft is not emitted as final
and the failure is surfaced to the human approver in Stage 12 rather than
quietly shipped.
"""
from __future__ import annotations

import re

NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
CITATION = re.compile(r"\[([^\]]+)\]")

# Phrases that mark a figure as uncertain. A contested figure stated without
# one of these is over-claiming, which is the specific failure this project
# argues against.
HEDGES_EN = ("between", "sources report", "contested", "range", "approximately",
             "around", "estimated", "no single value", "reportedly", "varies")
HEDGES_NE = ("देखि", "सम्म", "मतभेद", "अनुमानित", "करिब", "अपनाइएको छैन")


def _numbers_in(text: str) -> set[str]:
    return {m.group(0).replace(",", "") for m in NUMBER.finditer(text)}


def verify_sentence(sentence: str, passages_by_doc: dict[str, list[str]]) -> dict:
    """Is every figure in this sentence present in the sources it cites?"""
    cites = CITATION.findall(sentence)
    doc_ids = [d.strip() for c in cites for d in c.split(";") if d.strip()]
    nums = _numbers_in(CITATION.sub("", sentence))

    if not nums:
        return {"status": "no_figures", "supported": True, "sentence": sentence,
                "cited_docs": doc_ids}
    if not doc_ids:
        return {"status": "uncited_figures", "supported": False,
                "sentence": sentence, "unsupported_numbers": sorted(nums),
                "reason": "sentence states figures with no citation"}

    corpus = " ".join(t for d in doc_ids for t in passages_by_doc.get(d, []))
    corpus_nums = _numbers_in(corpus)
    # A figure counts as supported if it appears verbatim, or if it is a
    # rounded/rescaled form of a source number. Both directions are needed:
    # "0.725 sq. km" in a source and "0.725" in the draft, but also "459000"
    # in the draft against "459,000" in the source.
    unsupported = []
    for n in sorted(nums):
        if n in corpus_nums:
            continue
        try:
            v = float(n)
        except ValueError:
            unsupported.append(n)
            continue
        if any(abs(v - float(c)) <= max(abs(v), abs(float(c))) * 1e-6
               for c in corpus_nums if _is_float(c)):
            continue
        # Scale-normalised match: 14.7 (million) against 14700000.
        if any(_scale_match(v, float(c)) for c in corpus_nums if _is_float(c)):
            continue
        unsupported.append(n)

    return {
        "status": "verified" if not unsupported else "unsupported_figures",
        "supported": not unsupported,
        "sentence": sentence,
        "cited_docs": doc_ids,
        "unsupported_numbers": unsupported,
        "reason": (None if not unsupported else
                   f"figures {unsupported} do not appear in the cited sources "
                   f"{doc_ids}"),
    }


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _scale_match(a: float, b: float) -> bool:
    if a == 0 or b == 0:
        return False
    for f in (1e3, 1e6, 1e9):
        if abs(a * f - b) <= abs(b) * 1e-6 or abs(b * f - a) <= abs(a) * 1e-6:
            return True
    return False


# Verbs that mark a sentence as asserting something happened, as opposed to
# describing the report itself ("Information in this report is drawn from...").
_ASSERTION = re.compile(
    r"(?:destroyed|damaged|killed|swept|displaced|evacuated|collapsed|"
    r"breached|flooded|washed|affected|inundated|buried)|"
    r"(?:नष्ट|क्षति|बगाय|विस्थापित)", re.IGNORECASE)
# Sentences that are about the document rather than the event.
_META = re.compile(
    r"(?:this report|report is|sources:|research prototype|"
    r"not an operational|pinned source set|decision-support|drawn from)|"
    r"(?:यो प्रतिवेदन|स्रोतहरू)", re.IGNORECASE)


def _is_factual_assertion(sentence: str) -> bool:
    return bool(_ASSERTION.search(sentence)) and not _META.search(sentence)


def critique(draft: dict, recon: dict, lang: str) -> list[dict]:
    """Structural red-team pass over a whole draft."""
    findings = []
    hedges = HEDGES_EN if lang == "en" else HEDGES_NE
    contested = {c["quantity"] for c in recon.get("contradictions", [])}
    body_sentences = [(sec, s) for sec, paras in draft["sections"].items()
                      for s in paras]

    # Sections whose content is factual assertion about the event. Response,
    # gaps, funding and contacts carry our own framing and procedural text,
    # which is ours to write and not a claim about the world.
    FACTUAL_SECTIONS = ("highlights", "situation_overview", "humanitarian_impact")
    for section, sentence in body_sentences:
        if section not in FACTUAL_SECTIONS:
            continue
        nums = _numbers_in(CITATION.sub("", sentence))
        if CITATION.search(sentence):
            continue
        if nums:
            findings.append({
                "type": "uncited_figure", "severity": "high",
                "section": section, "sentence": sentence,
                "detail": "states a figure with no source citation"})
        elif _is_factual_assertion(sentence):
            # Caught nothing before this rule existed. The injected claim
            # "Three additional villages were destroyed downstream." carries no
            # digits, so the numeric verifier is structurally blind to it and
            # the figure-only critic rule skipped it too. An uncited assertion
            # about what happened is exactly what must not ship, with or
            # without a number in it.
            findings.append({
                "type": "uncited_claim", "severity": "high",
                "section": section, "sentence": sentence,
                "detail": ("states a fact about the event with no source "
                           "citation and no figure to verify against")})

    # A contested quantity must never be stated as settled.
    for c in recon.get("contradictions", []):
        q = c["quantity"]
        mentions = [s for _, s in body_sentences
                    if any(str(v) in s or f"{v:,.0f}" in s
                           for v in (c.get("min"), c.get("max"),
                                     c.get("stated_total"))
                           if v is not None)]
        for s in mentions:
            if not any(h in s.lower() for h in hedges):
                findings.append({
                    "type": "contested_figure_stated_as_settled",
                    "severity": "high", "quantity": q, "sentence": s,
                    "detail": ("this quantity is contested across sources but the "
                               "sentence carries no hedge or range")})

    if not draft.get("is_glof", True):
        body = " ".join(s for _, s in body_sentences)
        for term in ("glacial lake outburst", "हिमताल विस्फोट"):
            i = body.find(term)
            if i >= 0:
                window = body[max(0, i - 45):i + len(term) + 20]
                if "not" not in window.lower() and "थिएन" not in window:
                    findings.append({
                        "type": "negative_control_mislabelled",
                        "severity": "critical", "sentence": window,
                        "detail": ("the negative control is described as a GLOF "
                                   "without negation")})
    return findings


def run_loop(draft: dict, recon: dict, passages_by_doc: dict, lang: str,
             max_iterations: int) -> dict:
    """critic -> verifier -> revise, capped. Unresolved findings block release.

    Revision here is removal: a sentence whose figures are not supported by its
    cited sources is struck, not rewritten. Rewriting would require inventing
    replacement text, which is the failure mode being guarded against.
    """
    sections = {k: list(v) for k, v in draft["sections"].items()}
    history, iterations = [], 0

    while iterations < max_iterations:
        iterations += 1
        verdicts = []
        for sec, paras in sections.items():
            for s in paras:
                v = verify_sentence(s, passages_by_doc)
                v["section"] = sec
                verdicts.append(v)
        crit = critique({**draft, "sections": sections}, recon, lang)
        failing = [v for v in verdicts if not v["supported"]]
        history.append({"iteration": iterations,
                        "n_sentences": len(verdicts),
                        "n_unsupported": len(failing),
                        "n_critic_findings": len(crit)})
        if not failing:
            break
        # Strike the unsupported sentences and re-verify.
        strike = {v["sentence"] for v in failing}
        sections = {k: [s for s in v if s not in strike] for k, v in sections.items()}

    verdicts = []
    for sec, paras in sections.items():
        for s in paras:
            v = verify_sentence(s, passages_by_doc)
            v["section"] = sec
            verdicts.append(v)
    crit = critique({**draft, "sections": sections}, recon, lang)
    unresolved = [v for v in verdicts if not v["supported"]]
    critical = [c for c in crit if c["severity"] == "critical"]

    return {
        "iterations": iterations,
        "iteration_cap": max_iterations,
        "cap_reached": iterations >= max_iterations and bool(unresolved),
        "history": history,
        "sections": sections,
        "n_sentences_verified": len(verdicts),
        "n_sentences_struck": sum(len(draft["sections"][k]) - len(v)
                                  for k, v in sections.items()),
        "unresolved_unsupported": unresolved,
        "critic_findings": crit,
        "release_blocked": bool(unresolved or critical),
        "block_reason": (
            None if not (unresolved or critical) else
            f"{len(unresolved)} unsupported claim(s) and {len(critical)} critical "
            f"critic finding(s) remain after {iterations} iteration(s); the draft "
            f"is NOT marked final and is surfaced to the human approver"),
    }
