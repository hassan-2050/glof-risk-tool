"""Record the LLM response cache once, so `reproduce` never needs a key.

Run ONCE, with a key, outside the reproduce path:

    export GEMINI_API_KEY=...
    python -m src.data.record_llm_cache

Every prompt the pipeline will ever issue is enumerated here and its response
written to data/pinned/llm_cache/ and committed. Afterwards a judge clones the
repo, runs `make reproduce` with no key and no network, and gets identical
output, because the cache is the only source on that path and a miss is a hard
error rather than a silent live call.

This is the piece that makes an LLM-using pipeline honestly reproducible. The
usual alternative - "set your API key and re-run" - means every reviewer gets
different numbers from the ones in the write-up, and no one can tell whether a
discrepancy is model drift or a bug.
"""
from __future__ import annotations

import argparse

from src.common.config import REPO_ROOT, load_config
from src.common.io import read_json
from src.common.llm import CACHE_DIR, available, cache_stats, complete
from src.reporter.llm_critic import build_prompt


def back_translation_prompts() -> list[tuple[str, str]]:
    """(purpose, prompt) for every Nepali draft, for Stage 15's chrF++."""
    drafts_path = REPO_ROOT / "outputs" / "stage10_drafts.json"
    if not drafts_path.exists():
        raise SystemExit("run `python -m src.cli reproduce` first so the drafts "
                         "exist, then record the cache")
    drafts = read_json(drafts_path)["drafts"]
    PROSE = ("highlights", "situation_overview", "humanitarian_impact",
             "response", "gaps_and_constraints", "funding")
    out = []
    for key, d in sorted(drafts.items()):
        if not key.endswith("_ne"):
            continue
        body = " ".join(t for sec in PROSE for t in d["sections"].get(sec, []))
        out.append((
            "nepali_back_translation",
            "Translate the following Nepali humanitarian situation report "
            "into English. Preserve every number exactly. Output only the "
            "translation.\n\n" + body))
    return out


def critic_prompts() -> list[tuple[str, str]]:
    """(purpose, prompt) for the LLM half of the Stage 11 adversarial critic.

    The rule-based critic catches what we predicted; this asks a model to find
    what we did not. Its output is advisory - it cannot unblock a release, only
    add findings - because a model that can clear its own draft is not a check.
    """
    verif_path = REPO_ROOT / "outputs" / "stage11_verification.json"
    drafts_path = REPO_ROOT / "outputs" / "stage10_drafts.json"
    if not (verif_path.exists() and drafts_path.exists()):
        return []
    drafts = read_json(drafts_path)["drafts"]
    out = []
    for key, d in sorted(drafts.items()):
        if not key.endswith("_en"):
            continue
        # Shared builder, so the recorder and the caller cannot disagree. The
        # cache is keyed on a hash of the prompt; any divergence turns every
        # lookup into a silent miss.
        out.append(("adversarial_critic", build_prompt(d)))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true",
                   help="list the prompts that would be recorded")
    args = p.parse_args(argv)

    cfg = load_config()
    prompts = back_translation_prompts() + critic_prompts()
    print(f"prompts to record: {len(prompts)}")
    print(f"cache before: {cache_stats()}")

    if args.dry_run:
        for purpose, pr in prompts:
            print(f"  [{purpose}] {pr[:90]}...")
        return 0

    if not available():
        print("\nGEMINI_API_KEY (or GOOGLE_API_KEY) is not set.\n"
              "Set it and re-run; nothing was recorded.")
        return 2

    recorded = reused = 0
    for i, (purpose, pr) in enumerate(prompts, 1):
        r = complete(pr, cfg, purpose=purpose, allow_live=True)
        if r["cached"]:
            reused += 1
        else:
            recorded += 1
        print(f"  [{i}/{len(prompts)}] {purpose}: "
              f"{'cached' if r['cached'] else 'recorded'} ({r['key'][:8]})")

    print(f"\nrecorded {recorded}, already cached {reused}")
    print(f"cache after: {cache_stats()}")
    print(f"commit {CACHE_DIR.relative_to(REPO_ROOT).as_posix()} so reproduce "
          f"runs offline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
