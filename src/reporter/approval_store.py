"""Persistent record of real human approval decisions.

WHY THIS IS NOT THE LEDGER
--------------------------
Stage 12 deletes and rebuilds outputs/stage12_ledger.jsonl on every run - by
design, because the ledger is a derived artefact and `reproduce` must be
byte-identical. So a decision appended there by an interactive CLI would be
destroyed by the next `make reproduce`, silently, with no error. The gate would
look like it worked and would in fact record nothing.

Human decisions therefore live HERE, under data/, as a committed INPUT
alongside data/labels/ - the same status as the ground-truth files. Stage 12
reads this store and folds real decisions into the ledger it builds. The ledger
stays derived; the decisions stay durable.

DETERMINISM CONSTRAINTS, because these records enter a hashed artefact:
  * no floats - repr varies across platforms and the ledger recomputes its hash
    from the reloaded value
  * no wall-clock - the operator supplies a date, or it is omitted
  * sorted keys, LF endings, UTF-8, ensure_ascii=False, matching the ledger's
    own serialisation exactly
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.common.config import REPO_ROOT

STORE_PATH = REPO_ROOT / "data" / "approvals" / "decisions.jsonl"

VALID_DECISIONS = ("approved", "rejected", "approved_with_reservations")


def _record_hash(rec: dict) -> str:
    """Integrity digest over the decision content.

    Lets Stage 12 detect a hand-edited decision file. Same serialisation rule
    as the ledger: sort_keys, no indent, ensure_ascii=False.
    """
    body = {k: v for k, v in rec.items() if k != "record_hash"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load(path: Path | None = None) -> dict:
    """All recorded decisions, keyed by draft. Last write wins.

    Returns {draft_key: record}. A malformed line is skipped and counted rather
    than raising - a corrupt store must not make the whole pipeline unrunnable,
    but it must be visible, so the count travels in the result.
    """
    path = path or STORE_PATH
    decisions: dict[str, dict] = {}
    skipped = 0
    tampered: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if "draft" not in rec or "decision" not in rec:
                skipped += 1
                continue
            if rec.get("record_hash") and rec["record_hash"] != _record_hash(rec):
                tampered.append(rec["draft"])
            decisions[rec["draft"]] = rec
    return {"decisions": decisions, "skipped_lines": skipped,
            "tampered": sorted(tampered), "path": str(path)}


def append(record: dict, path: Path | None = None) -> dict:
    """Append one decision. Caller supplies every field; nothing is invented.

    No timestamp is generated here. A clock reading would differ between the
    operator's machine and a reproduction, and this record is consumed by a
    hashed artefact. The operator may pass `decided_on` explicitly.
    """
    path = path or STORE_PATH
    if record.get("decision") not in VALID_DECISIONS:
        raise ValueError(f"decision must be one of {VALID_DECISIONS}")
    for key in ("draft", "approver"):
        if not record.get(key):
            raise ValueError(f"{key} is required")
    for k, v in record.items():
        if isinstance(v, float):
            raise ValueError(
                f"field {k!r} is a float; decision records must be float-free "
                "because the ledger recomputes its hash from the reloaded value "
                "and float repr is not stable across platforms")

    rec = dict(record)
    rec["record_hash"] = _record_hash(rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(rec, sort_keys=True, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
    return rec


def decision_for(draft_key: str, store: dict | None = None) -> dict | None:
    store = store or load()
    return store["decisions"].get(draft_key)
