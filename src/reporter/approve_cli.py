"""Interactive human-approval checkpoint. NEVER runs inside `reproduce`.

Closes the gap the config comment admitted: until now the approver was the
string "duty-officer (simulated)" and no human was ever actually asked. The
gate recorded a decision that nobody made.

This shows the officer what they are signing off - the contested figures, the
verifier's unresolved claims, the critic's findings - and requires them to type
their name and a decision. It refuses to accept a bare Enter as approval.

Run:  python -m src.cli approve                # every draft awaiting a decision
      python -m src.cli approve --draft thame_2024_en
      python -m src.cli approve --list         # show status, decide nothing

Deliberately separate from `reproduce`:
  * reproduce is non-interactive and must stay that way
  * reproduce is byte-identical, and a prompt is not
  * decisions persist to data/approvals/decisions.jsonl, which reproduce READS
    but never writes, so a decision survives the next run
"""
from __future__ import annotations

import sys

from src.common.config import REPO_ROOT, load_config
from src.common.io import read_json
from src.reporter import approval_store

BAR = "─" * 72


def _fmt_money(v) -> str:
    """Format a figure without destroying it.

    A plain ',.0f' rounded the Rasuwa lake area contradiction to "0 to 1" -
    the real range is 0.435 to 0.75 km2, and those two numbers are exactly what
    the officer is being asked to weigh. Small magnitudes keep their
    significant digits.
    """
    if not isinstance(v, (int, float)):
        return str(v)
    if v != 0 and abs(v) < 10:
        return f"{v:,.3g}"
    return f"{v:,.0f}"


def _brief(draft_key: str, retrieval: dict, recon: dict, verif: dict,
           drafts: dict) -> list[str]:
    """Everything the officer needs to see before deciding."""
    eid, lang = draft_key.rsplit("_", 1)
    ev = retrieval["events"][eid]
    rc = recon["events"][eid]
    v = verif["drafts"][draft_key]
    d = drafts[draft_key]

    out = [BAR, f"  DRAFT   {draft_key}", f"  EVENT   {ev['title']}",
           f"  PLACE   {ev['admin']}, {ev['country']}",
           f"  TYPE    {'glacial lake outburst flood' if ev['is_glof'] else 'NOT a GLOF'}",
           BAR]

    out.append(f"\n  VERIFICATION  {v['n_sentences_verified']} sentences checked, "
               f"{v['n_sentences_struck']} struck over {v['iterations']} "
               f"iteration(s) of a {v['iteration_cap']} cap")
    if v["release_blocked"]:
        out.append(f"  ** RELEASE BLOCKED: {v['block_reason']}")
    unresolved = v["unresolved_unsupported"]
    if unresolved:
        out.append(f"  ** {len(unresolved)} UNSUPPORTED CLAIM(S) REMAIN:")
        for u in unresolved[:5]:
            out.append(f"       - {u['sentence'][:100]}")
    else:
        out.append("  no unsupported claims remain")

    crit = v["critic_findings"]
    if crit:
        out.append(f"\n  CRITIC  {len(crit)} finding(s):")
        for f in crit[:6]:
            out.append(f"       [{f['severity']}] {f['type']}: {f['sentence'][:80]}")

    llm = v.get("llm_critic") or {}
    if llm.get("available"):
        first = (llm.get("findings_text") or "").strip().splitlines()
        out.append("\n  ADVISORY MODEL REVIEW (cannot block release):")
        for line in [l for l in first if l.strip()][:4]:
            out.append(f"       {line[:100]}")

    if rc["contradictions"]:
        out.append(f"\n  CONTESTED FIGURES  {len(rc['contradictions'])} - reported as "
                   f"ranges, no single value adopted:")
        for c in rc["contradictions"]:
            if "stated_total" in c:
                out.append(f"       [{c['severity']}] {c['quantity']}: "
                           f"{c['publisher'].split(' (')[0]} states "
                           f"{_fmt_money(c['stated_total'])}, itemises "
                           f"{_fmt_money(c['itemised_sum'])}")
            else:
                pubs = sorted({v2["publisher"].split(" (")[0] for v2 in c["values"]})
                out.append(f"       [{c['severity']}] {c['quantity']}: "
                           f"{_fmt_money(c['min'])} to {_fmt_money(c['max'])} "
                           f"across {', '.join(pubs)}")

    out.append(f"\n  DRAFT TEXT  outputs/sitreps/{eid}_{lang}.md "
               f"({d['word_count']} words)")
    out.append(BAR)
    return out


def _prompt(question: str, valid=None) -> str:
    """Read one answer. Refuses to treat an empty line as assent."""
    while True:
        try:
            ans = input(question).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nno decision recorded.")
            raise SystemExit(130)
        if not ans:
            print("  a blank answer is not a decision - type a value, or Ctrl-C to abort.")
            continue
        if valid and ans.lower() not in valid:
            print(f"  expected one of: {', '.join(valid)}")
            continue
        return ans


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        prog="glof approve", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--draft", help="decide a single draft, e.g. thame_2024_en")
    p.add_argument("--list", action="store_true",
                   help="show decision status and exit without deciding")
    args = p.parse_args(argv)

    cfg = load_config()
    out = REPO_ROOT / "outputs"
    needed = ["stage08_retrieval.json", "stage09_reconciliation.json",
              "stage10_drafts.json", "stage11_verification.json"]
    missing = [n for n in needed if not (out / n).exists()]
    if missing:
        print(f"missing pipeline outputs: {missing}\n"
              f"run `python -m src.cli reproduce` first.", file=sys.stderr)
        return 2

    retrieval = read_json(out / needed[0])
    recon = read_json(out / needed[1])
    drafts = read_json(out / needed[2])["drafts"]
    verif = read_json(out / needed[3])

    store = approval_store.load()
    recorded = store["decisions"]
    if store["tampered"]:
        print(f"WARNING: decision records failed their integrity hash: "
              f"{store['tampered']}\n", file=sys.stderr)

    keys = sorted(drafts)
    if args.draft:
        if args.draft not in drafts:
            print(f"unknown draft {args.draft!r}. Known: {keys}", file=sys.stderr)
            return 2
        keys = [args.draft]

    if args.list:
        print(f"{'draft':<26}{'verification':<14}{'human decision':<26}approver")
        for k in sorted(drafts):
            v = verif["drafts"][k]
            status = "BLOCKED" if v["release_blocked"] else "passed"
            rec = recorded.get(k)
            print(f"{k:<26}{status:<14}"
                  f"{(rec['decision'] if rec else 'not yet decided'):<26}"
                  f"{rec['approver'] if rec else '-'}")
        print(f"\nstore: {store['path']}")
        print(f"{sum(1 for k in drafts if k in recorded)}/{len(drafts)} drafts "
              f"have a recorded human decision.")
        return 0

    pending = [k for k in keys if k not in recorded]
    if not pending:
        print("every selected draft already has a recorded decision. "
              "Use --list to review, or --draft to re-decide one.")
        return 0

    print(f"\n{len(pending)} draft(s) awaiting a human decision.\n")
    for key in pending:
        v = verif["drafts"][key]
        for line in _brief(key, retrieval, recon, verif, drafts):
            print(line)

        if v["release_blocked"]:
            print("\n  This draft FAILED verification. It is withheld from "
                  "approval and cannot be approved here.")
            print("  Recording the withholding so it is auditable.\n")
            approver = _prompt("  your name (recording the withholding): ")
            approval_store.append({
                "draft": key, "decision": "rejected", "approver": approver,
                "reason": "withheld: " + str(v.get("block_reason")),
                "verification_blocked": True,
            })
            print("  recorded.\n")
            continue

        print("\n  Decide:  approve  |  reject  |  reserve  (approve with reservations)")
        choice = _prompt("  decision: ",
                         valid={"approve", "reject", "reserve"})
        decision = {"approve": "approved", "reject": "rejected",
                    "reserve": "approved_with_reservations"}[choice]
        approver = _prompt("  your name: ")
        reason = ""
        if decision != "approved":
            reason = _prompt("  reason (required for reject / reservations): ")
        note = input("  optional note (Enter to skip): ").strip()
        on = input("  date decided YYYY-MM-DD (Enter to omit): ").strip()

        rec = {"draft": key, "decision": decision, "approver": approver,
               "verification_blocked": False}
        if reason:
            rec["reason"] = reason
        if note:
            rec["note"] = note
        if on:
            rec["decided_on"] = on
        approval_store.append(rec)
        print(f"  recorded: {decision} by {approver}\n")

    print(f"decisions written to {approval_store.STORE_PATH.relative_to(REPO_ROOT).as_posix()}")
    print("`make reproduce` will read them; it never writes to this file.")
    return 0
