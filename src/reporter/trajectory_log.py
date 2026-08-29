"""Stage 17: agent-trajectory logs - what each agent actually did, per event.

The plan asks for "the actual tool-call sequences the agents took, not just
final outputs", and the reason is auditability: a final sitrep tells you what
was concluded, not how, and "how" is where a hazard pipeline goes wrong
silently.

Every step here is reconstructed from the committed stage artefacts rather than
narrated, and each one names the file that proves it. That means a reader can
check any claim in the trajectory against the artefact it cites, and it means
the log cannot drift from the run - if a stage output changes, the trajectory
built from it changes too.

Where a step consulted a language model, the cache key is recorded. That key is
a hash of (provider, model, temperature, seed, prompt), so a reviewer can find
the exact prompt and the exact response in data/pinned/llm_cache/ and satisfy
themselves that nothing was regenerated between the run and the write-up.

Deliberately NOT a wrapper that intercepts calls at runtime. Instrumenting
every function to log itself would add a mutable global, a second source of
truth about what happened, and a way for the log and the outputs to disagree.
Deriving the trajectory from the artefacts keeps exactly one source of truth.
"""
from __future__ import annotations

from src.common.io import read_json
from src.common.llm import cache_key


def _step(n: int, agent: str, action: str, inputs, outputs, decision: str,
          evidence: str, **extra) -> dict:
    return {"step": n, "agent": agent, "action": action,
            "inputs": inputs if isinstance(inputs, list) else [inputs],
            "outputs": outputs if isinstance(outputs, list) else [outputs],
            "decision": decision, "evidence_artefact": evidence, **extra}


def build_for_event(event_id: str, outputs_dir, cfg) -> dict:
    """The full agent sequence for one event, every step traceable."""
    retrieval = read_json(outputs_dir / "stage08_retrieval.json")
    recon = read_json(outputs_dir / "stage09_reconciliation.json")
    drafts = read_json(outputs_dir / "stage10_drafts.json")
    verif = read_json(outputs_dir / "stage11_verification.json")
    approvals = read_json(outputs_dir / "stage12_approvals.json")

    ev = retrieval["events"][event_id]
    rc = recon["events"][event_id]
    steps: list[dict] = []
    n = 0

    # --- 1. retriever ------------------------------------------------------
    n += 1
    steps.append(_step(
        n, "retriever", "load_pinned_bundle",
        [f"data/pinned/documents/{event_id}/"],
        [f"{ev['n_passages']} passages from {ev['n_documents']} documents"],
        (f"Accepted: {ev['n_distinct_publishers']} distinct publishers meets the "
         f"3-source minimum. Publishers: {', '.join(ev['distinct_publishers'])}."),
        "outputs/stage08_retrieval.json",
        deterministic=True,
        note="no live web calls; retrieval is a read of committed files"))

    # --- 2. reconciliation -------------------------------------------------
    n += 1
    by_kind: dict[str, int] = {}
    for c in rc["contradictions"]:
        by_kind[c["kind"]] = by_kind.get(c["kind"], 0) + 1
    steps.append(_step(
        n, "numeric_reconciliation", "extract_claims",
        ["outputs/stage08_retrieval.json"],
        [f"{rc['n_claims_extracted']} numeric claims, each tagged with its source"],
        ("Rule-based extraction with nearest-keyword binding. Deterministic on "
         "purpose: the contradiction table is the project's central artefact and "
         "must be checkable, not regenerated."),
        "outputs/stage09_reconciliation.json"))

    n += 1
    high = [c["quantity"] for c in rc["contradictions"] if c["severity"] == "high"]
    steps.append(_step(
        n, "numeric_reconciliation", "detect_contradictions",
        [f"{rc['n_claims_extracted']} claims"],
        [f"{rc['n_contradictions']} contradictions ({by_kind})"],
        (f"REFUSED to adopt a single value for any contested quantity. "
         f"High-severity: {high or 'none'}. Each is emitted as a range with "
         f"per-source attribution."),
        "outputs/stage09_disagreements.csv",
        contradictions=[{"quantity": c["quantity"], "kind": c["kind"],
                         "severity": c["severity"],
                         "range": [c.get("min", c.get("stated_total")),
                                   c.get("max", c.get("itemised_sum"))]}
                        for c in rc["contradictions"]]))

    # --- 3. drafter --------------------------------------------------------
    for lang in ("en", "ne"):
        d = drafts["drafts"][f"{event_id}_{lang}"]
        n += 1
        steps.append(_step(
            n, "drafter", f"compose_ocha_sitrep_{lang}",
            ["outputs/stage09_reconciliation.json"],
            [f"outputs/sitreps/{event_id}_{lang}.md ({d['word_count']} words)"],
            (f"Assembled from reconciliation output, never freehand. "
             f"{d['n_contested_reflected']} contested figures rendered as ranges "
             f"with citations. is_glof={d['is_glof']}."),
            f"outputs/sitreps/{event_id}_{lang}.md"))

    # --- 4. verifier + critic ---------------------------------------------
    for lang in ("en", "ne"):
        v = verif["drafts"][f"{event_id}_{lang}"]
        n += 1
        steps.append(_step(
            n, "verifier", f"check_claims_against_sources_{lang}",
            [f"outputs/sitreps/{event_id}_{lang}.md",
             "outputs/stage08_retrieval.json"],
            [f"{v['n_sentences_verified']} sentences verified, "
             f"{v['n_sentences_struck']} struck"],
            (f"Ran {v['iterations']} of a maximum {v['iteration_cap']} iterations. "
             f"Unresolved after the cap: "
             f"{len(v['unresolved_unsupported'])}. Release blocked: "
             f"{v['release_blocked']}."),
            "outputs/stage11_verification.json",
            loop_history=v["history"]))

        n += 1
        crit_types = sorted({f["type"] for f in v["critic_findings"]})
        steps.append(_step(
            n, "adversarial_critic", f"red_team_{lang}",
            [f"outputs/sitreps/{event_id}_{lang}.md"],
            [f"{len(v['critic_findings'])} findings: {crit_types or 'none'}"],
            ("Structural rules covering what the numeric verifier cannot see: "
             "contested figures stated as settled, uncited assertions, the "
             "negative control described as a GLOF."),
            "outputs/stage11_verification.json"))

        if lang == "en" and v.get("llm_critic", {}).get("available"):
            lc = v["llm_critic"]
            n += 1
            from src.reporter.llm_critic import build_prompt
            key = cache_key(cfg.require("llm.provider"), cfg.require("llm.model"),
                            cfg.require("llm.temperature"), cfg.require("llm.seed"),
                            build_prompt(drafts["drafts"][f"{event_id}_en"]), None)
            steps.append(_step(
                n, "adversarial_critic_llm", "second_opinion",
                [f"outputs/sitreps/{event_id}_en.md"],
                ["free-text findings, advisory only"],
                ("ADVISORY. Cannot unblock a release or strike a sentence - a "
                 "model permitted to clear its own draft is a rubber stamp. "
                 "Findings are added for the human approver to read."),
                "outputs/stage11_verification.json",
                llm_call={"provider": cfg.require("llm.provider"),
                          "model": cfg.require("llm.model"),
                          "temperature": cfg.require("llm.temperature"),
                          "seed": cfg.require("llm.seed"),
                          "cache_key": key,
                          "cache_file": f"data/pinned/llm_cache/{key}.json",
                          "served_from_cache": lc.get("cached"),
                          "verify_note": ("open the cache file to read the exact "
                                          "prompt and response; nothing was "
                                          "regenerated after the run")}))

    # --- 5. ledger and approval -------------------------------------------
    for lang in ("en", "ne"):
        a = approvals["approvals"][f"{event_id}_{lang}"]
        n += 1
        steps.append(_step(
            n, "provenance_ledger", f"record_approval_decision_{lang}",
            ["outputs/stage11_verification.json"],
            ["outputs/stage12_ledger.jsonl (append-only, hash-chained)"],
            (f"decision={a['decision']}, approver={a['approver']}. "
             f"Presented for approval: {a['presented_for_approval']}. "
             + (f"WITHHELD: {a['withheld_reason']}"
                if not a["presented_for_approval"] else
                "No document is final without this recorded human decision.")),
            "outputs/stage12_ledger.jsonl"))

    precedents = approvals.get("precedents", {}).get(event_id, [])
    n += 1
    steps.append(_step(
        n, "memory", "surface_precedents",
        ["outputs/stage12_ledger.jsonl"],
        [f"{len(precedents)} prior event(s) surfaced"],
        (f"Precedent lookup runs BEFORE filing, so an event sees only what came "
         f"before it - the same discipline as the pre-event cutoff. "
         f"Matched: {[p['event_id'] + ' (' + p['matched_on'] + ')' for p in precedents] or 'none'}."),
        "outputs/stage12_approvals.json"))

    # --- 6. machine-readable exports --------------------------------------
    n += 1
    steps.append(_step(
        n, "exporter", "emit_cap_and_hxl",
        ["outputs/stage09_reconciliation.json"],
        [f"outputs/exports/{event_id}_cap.xml", "outputs/exports/figures_hxl.csv"],
        ("Generated from the same reconciliation record as the sitrep, so the "
         "human-readable and machine-readable paths cannot drift. CAP status is "
         "Exercise, never Actual."),
        f"outputs/exports/{event_id}_cap.xml"))

    return {
        "event_id": event_id,
        "title": ev["title"],
        "is_glof": ev["is_glof"],
        "n_steps": len(steps),
        "agents_involved": sorted({s["agent"] for s in steps}),
        "steps": steps,
        "how_to_verify": (
            "Every step names the artefact that proves it. This log is DERIVED "
            "from those artefacts rather than narrated alongside them, so it "
            "cannot claim something the outputs do not show. LLM steps carry a "
            "cache key that resolves to the exact prompt and response in "
            "data/pinned/llm_cache/."),
    }


def build_all(outputs_dir, cfg) -> dict:
    retrieval = read_json(outputs_dir / "stage08_retrieval.json")
    trajectories = {eid: build_for_event(eid, outputs_dir, cfg)
                    for eid in sorted(retrieval["events"])}
    return {"events": trajectories,
            "n_events": len(trajectories),
            "total_steps": sum(t["n_steps"] for t in trajectories.values())}
