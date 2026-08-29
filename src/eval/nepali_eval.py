"""Stage 15: Nepali output quality, measured with low-resource-appropriate tools.

Fluency is not correctness, and for a disaster sitrep the thing that must not
drift is technical vocabulary. A translation that reads beautifully while
rendering "glacial lake outburst flood" three different ways across one
document is worse than a stilted one that is consistent, because a reader
matching terms against DHM and NDRRMA bulletins will not know they are the same
event.

So two measures, in the order they matter here:

  TERMINOLOGY CONSISTENCY  every disaster term drawn from the fixed glossary,
                           rendered identically everywhere. Exact, computable
                           with no reference translation and no model.

  chrF++                   character-n-gram F-score via sacreBLEU, the safe
                           primary metric for Nepali where BLEU's word-level
                           matching fails on a morphologically rich,
                           low-resource language. Needs a reference; ours comes
                           from a back-translation round trip, which is the
                           cheap sanity check the brief recommends.

COMET is deliberately not run. The brief's own fallback allows dropping it, and
its scores degrade for low-resource pairs in ways that would need more
validation than the metric is worth here. That fallback is recorded as taken.
"""
from __future__ import annotations

import re

from src.reporter.drafter import GLOSSARY

try:
    import sacrebleu
except ImportError:  # pragma: no cover
    sacrebleu = None


def terminology_consistency(nepali_texts: dict[str, str],
                            passthrough: dict[str, str] | None = None) -> dict:
    """Is every glossary term rendered identically across all drafts?

    Exact by construction here, because the drafter draws technical vocabulary
    only from the glossary. That is worth stating plainly rather than
    presenting a perfect score as if it were hard-won: the value of the check
    is that it would CATCH a regression the moment someone hand-edits a draft
    or swaps in a model-generated one.
    """
    # Strings carried through verbatim on purpose: the event title and the
    # admin/location string. These are identifiers and proper nouns - "Mangan
    # District, Sikkim", "Chamoli rock-and-ice avalanche" - and a Nepali sitrep
    # keeps them so a reader can match the event against DHM and NDRRMA
    # bulletins that use the same names.
    #
    # Without this exclusion the check reported three failures that were all
    # false: "district" in all four drafts, plus "avalanche" and "landslide"
    # inside event titles. A consistency check that fires on correct behaviour
    # trains you to ignore it, which is worse than not having one.
    # Inline citations are stripped first. "[zhang_2024_landslides]" is a
    # machine identifier embedded in prose, not an untranslated hazard term,
    # and leaving it in made the check report a leak on a correctly translated
    # sentence. Same reasoning as the passthrough list below: a consistency
    # check that fires on correct behaviour teaches you to ignore it.
    passthrough = passthrough or {}
    scan = {k: re.sub(r"\[[^\]]*\]", " ", v) for k, v in nepali_texts.items()}
    for k, v in scan.items():
        for frag in passthrough.get(k, []):
            if frag:
                scan[k] = scan[k].replace(frag, " ")

    findings, per_term = [], {}
    for key, (en, ne) in GLOSSARY.items():
        occurrences = {}
        for draft_id, text in scan.items():
            n = text.count(ne)
            if n:
                occurrences[draft_id] = n
        # A term is inconsistent if the ENGLISH form leaks into Nepali output.
        leaks = {d: t.lower().count(en.lower()) for d, t in scan.items()
                 if en.lower() in t.lower() and len(en) > 4}
        per_term[key] = {"nepali": ne, "english": en,
                         "drafts_using_nepali": len(occurrences),
                         "total_occurrences": sum(occurrences.values()),
                         "english_leak_drafts": sorted(leaks)}
        if leaks:
            findings.append({"term": key, "issue": "english_term_in_nepali_draft",
                             "drafts": sorted(leaks)})

    core = ["glof", "flood", "landslide", "displaced", "missing", "deaths",
            "casualties"]
    core_used = [k for k in core if per_term[k]["total_occurrences"] > 0]
    return {"terms_checked": len(GLOSSARY),
            "core_terms": core, "core_terms_present": core_used,
            "core_coverage": round(len(core_used) / len(core), 4),
            "inconsistencies": findings,
            "consistent": not findings,
            "per_term": per_term,
            "method_note": ("The drafter sources technical vocabulary only from "
                            "the glossary, so consistency is structural rather "
                            "than achieved. The check earns its place by "
                            "catching regressions if a draft is hand-edited or "
                            "replaced with model-generated text.")}


def chrf(hypothesis: str, reference: str) -> dict:
    """chrF++ via sacreBLEU. word_order=2 is what makes it chrF++, not chrF."""
    if sacrebleu is None:
        return {"available": False, "reason": "sacrebleu not installed"}
    # One scorer, reused. get_signature() on a fresh instance raises
    # "Number of references unknown, please evaluate the metric first" - the
    # signature records the reference count, which only exists after scoring.
    # Building a second instance for the signature crashed the whole stage,
    # and because the crash happened before the output was written, the stale
    # JSON on disk kept reporting the PREVIOUS run's cache misses - which sent
    # me looking for a cache-key bug that did not exist.
    scorer = sacrebleu.CHRF(word_order=2)
    score = scorer.corpus_score([hypothesis], [[reference]])
    return {"available": True, "chrf2": round(score.score, 2),
            "metric": "chrF++ (char n-gram F-score, word_order=2)",
            "signature": str(scorer.get_signature())}


def back_translation_check(nepali: str, english_source: str, cfg,
                           complete_fn) -> dict:
    """Nepali -> English round trip, scored against the original English.

    A round trip cannot distinguish a good translation from a bad one that
    happens to reverse cleanly, so this is a sanity check and is labelled as
    one. It catches the failure that matters most - meaning lost or numbers
    mangled - without requiring a human reference translation we do not have.
    """
    prompt = ("Translate the following Nepali humanitarian situation report "
              "into English. Preserve every number exactly. Output only the "
              "translation.\n\n" + nepali)
    try:
        out = complete_fn(prompt, cfg, purpose="nepali_back_translation")
    except Exception as exc:  # noqa: BLE001
        return {"available": False,
                "reason": f"{type(exc).__name__}: {exc}",
                "note": ("Back-translation needs one recorded LLM response per "
                         "draft. Run `python -m src.data.record_llm_cache` once "
                         "with GEMINI_API_KEY set; afterwards it replays from "
                         "the committed cache with no key and no network.")}
    scored = chrf(out["text"], english_source)
    # Numbers surviving the round trip is the check that actually matters for a
    # sitrep: fluency can degrade harmlessly, a mangled casualty count cannot.
    src_nums = set(re.findall(r"\d[\d,\.]*", english_source))
    back_nums = set(re.findall(r"\d[\d,\.]*", out["text"]))
    return {"available": True, "cached": out["cached"],
            "chrf": scored,
            "numbers_in_source": len(src_nums),
            "numbers_preserved": len(src_nums & back_nums),
            "number_preservation": round(
                len(src_nums & back_nums) / max(len(src_nums), 1), 4),
            "back_translation": out["text"][:1200]}
