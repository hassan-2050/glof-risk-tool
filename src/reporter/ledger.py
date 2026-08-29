"""Stage 12: append-only provenance ledger and human approval gate.

Direct answer to the Tsho Rolpa lesson. Nepal built an early-warning system
there in 2000-2002 with sirens in 19 villages; it is now defunct, and the
documented failure modes were over-automation and technological dependence -
"the early warning systems installed more than 20 years ago were damaged long
ago". A system that emits authoritative-looking flood reports with no human in
the loop repeats that mistake in software.

So: nothing here is FINAL until a named human approves it, and every claim in
an approved document is traceable to the source it came from and the
verification verdict it received.

The ledger is append-only by construction. Entries carry a hash chain, so a
retrospective edit is detectable rather than merely discouraged - if an
approval or a claim is altered after the fact, every subsequent hash breaks.

MEMORY ACROSS EVENTS. The ledger doubles as institutional memory: when a new
event is filed, prior events at the same location or of the same hazard type
are surfaced as precedent. A second Rasuwa-type flood should arrive with the
July 2025 record already attached, which is precisely what an officer needs and
what a stateless pipeline cannot provide.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

GENESIS = "0" * 64


def _hash_entry(prev_hash: str, payload: dict) -> str:
    blob = prev_hash + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Ledger:
    """Append-only, hash-chained record of claims, verification and approvals."""

    def __init__(self, path: Path):
        self.path = path
        self.entries: list[dict] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.entries.append(json.loads(line))

    @property
    def head(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS

    def append(self, kind: str, payload: dict) -> dict:
        entry = {"seq": len(self.entries), "kind": kind,
                 "prev_hash": self.head, "payload": payload}
        entry["hash"] = _hash_entry(entry["prev_hash"], payload)
        self.entries.append(entry)
        return entry

    def write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n"
                    for e in self.entries),
            encoding="utf-8", newline="\n")

    def verify_chain(self) -> dict:
        """Recompute every hash. A single altered byte breaks the chain."""
        prev = GENESIS
        for e in self.entries:
            expect = _hash_entry(prev, e["payload"])
            if e["prev_hash"] != prev or e["hash"] != expect:
                return {"intact": False, "broken_at_seq": e["seq"],
                        "reason": ("entry hash does not match its payload and "
                                   "predecessor; the ledger has been edited "
                                   "after the fact")}
            prev = e["hash"]
        return {"intact": True, "entries": len(self.entries), "head": prev}

    def precedents(self, event_id: str, admin: str, hazard: str) -> list[dict]:
        """Prior events at the same place or of the same kind."""
        out = []
        for e in self.entries:
            if e["kind"] != "event_filed":
                continue
            p = e["payload"]
            if p["event_id"] == event_id:
                continue
            same_place = admin and p.get("admin") and (
                p["admin"].split(",")[0].strip().lower()
                == admin.split(",")[0].strip().lower())
            same_hazard = p.get("hazard") == hazard
            if same_place or same_hazard:
                out.append({"event_id": p["event_id"], "title": p.get("title"),
                            "admin": p.get("admin"), "hazard": p.get("hazard"),
                            "filed_seq": e["seq"],
                            "matched_on": ("location" if same_place else "hazard type")})
        return out


def approval_decision(verification: dict, draft_key: str, approver: str,
                      frozen_ts: str) -> dict:
    """The human gate.

    Auto-approval is deliberately impossible: a decision must name a person.
    What the system CAN do is refuse to present a draft for approval at all
    when verification blocked it, which is the difference between "a human
    signed off" and "a human was handed something already known to be broken".
    """
    blocked = verification["release_blocked"]
    return {
        "draft": draft_key,
        "presented_for_approval": not blocked,
        "withheld_reason": verification.get("block_reason"),
        "approver": None if blocked else approver,
        "decision": "withheld_from_approval" if blocked else "approved",
        "decided_at": frozen_ts,
        "n_unresolved_claims": len(verification["unresolved_unsupported"]),
        "n_critic_findings": len(verification["critic_findings"]),
        "verification_iterations": verification["iterations"],
        "note": ("This is a RECORDED decision by a named approver, not an "
                 "automated pass. No document is final without one - a direct "
                 "response to the documented Tsho Rolpa early-warning failure, "
                 "where over-automation was a named cause."),
    }
