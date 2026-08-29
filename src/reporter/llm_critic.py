"""The LLM half of the Stage 11 adversarial critic. Strictly advisory.

The rule-based critic in critic.py catches the failures we anticipated and
encoded. This asks a model to find the ones we did not.

It cannot clear a draft, unblock a release, or strike a sentence. A model that
is allowed to approve its own output is not a check, it is a rubber stamp with
extra steps, so its findings only ever ADD to the review that a human reads at
the Stage 12 approval gate.

When the prompt is not in the committed cache the result is `unavailable`
rather than an error, so a judge with no API key gets the same pipeline, the
same deterministic verdict, and an explicit note about what was skipped.
"""
from __future__ import annotations

PROMPT_HEADER = (
    "You are a red-team reviewer of humanitarian situation reports. "
    "Find every claim that is unsupported, over-confident, or missing a "
    "hedge. Be specific and quote the sentence. If a figure is stated "
    "as settled when sources disagree, say so. Do not rewrite the "
    "report.\n\n"
)


def build_prompt(draft: dict) -> str:
    """Render a draft for review. Must match record_llm_cache.py exactly.

    The cache is keyed on a hash of the prompt, so any divergence between the
    recorder and this caller silently turns every lookup into a miss.
    """
    body = "\n".join(
        "## " + section + "\n" + "\n".join(paragraphs)
        for section, paragraphs in draft["sections"].items()
    )
    return PROMPT_HEADER + body


def llm_critique(draft: dict, cfg, complete_fn) -> dict:
    """Second opinion from a model, recorded but never authoritative."""
    prompt = build_prompt(draft)
    try:
        out = complete_fn(prompt, cfg, purpose="adversarial_critic")
    except Exception as exc:  # noqa: BLE001 - absence of a key must not fail the run
        return {
            "available": False,
            "advisory_only": True,
            "reason": f"{type(exc).__name__}: {str(exc)[:200]}",
            "note": ("The deterministic critic and verifier ran regardless; "
                     "only this advisory second opinion is missing."),
        }
    return {
        "available": True,
        "cached": out["cached"],
        "advisory_only": True,
        "cannot_unblock_release": True,
        "findings_text": out["text"],
        "note": ("Advisory. Adds findings for the human approver in Stage 12; "
                 "never clears a draft and never strikes a sentence."),
    }
