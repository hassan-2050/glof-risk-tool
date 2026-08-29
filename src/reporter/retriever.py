"""Stage 8: retriever agent over the committed document bundles.

Deliberately deterministic and offline. Retrieval here is not the interesting
part of the problem - the bundles are small and fully pinned - and making it a
similarity search over embeddings would add nondeterminism, a model dependency
and a failure mode, in exchange for nothing this project is trying to
demonstrate. What the downstream agents need is every passage, with its
provenance intact and in a stable order.

The one thing this stage must get right is that provenance survives. Every
passage leaves here carrying publisher, document type, publication date, URL,
DOI and licence, plus whether it is a verbatim quotation or our own summary.
The reconciliation and drafting agents can then attribute a figure without ever
re-reading the source, and a claim in the final sitrep can be traced back to a
publisher without a second lookup.
"""
from __future__ import annotations

from src.common.io import read_json


def retrieve_event(event_id: str, docs_root, cfg) -> dict:
    """All passages for one event, with per-source metadata attached."""
    manifest = read_json(docs_root / "MANIFEST.json")
    ev = manifest["events"].get(event_id)
    if ev is None:
        return {"event_id": event_id, "error": "unknown event", "passages": []}

    passages = []
    # Sorted by doc_id so ordering is a property of the data, not of the
    # filesystem, which is what makes the repeat-run check meaningful.
    for d in sorted(ev["documents"], key=lambda d: d["doc_id"]):
        doc = read_json(docs_root / event_id / f"{d['doc_id']}.json")
        src = doc["source"]
        for p in doc["passages"]:
            passages.append({
                "passage_id": p["passage_id"],
                "doc_id": doc["doc_id"],
                "text": p["text"],
                "kind": p["kind"],
                "carries_figures": p.get("carries_figures", []),
                "source": {
                    "publisher": src["publisher"],
                    "doc_type": src["doc_type"],
                    "published": src["published"],
                    "url": src["url"],
                    "doi": src.get("doi"),
                    "authors": src.get("authors", []),
                    "licence": src["licence"],
                },
                "notes": doc.get("notes", {}),
            })

    publishers = sorted({p["source"]["publisher"] for p in passages})
    return {
        "event_id": event_id,
        "title": ev["title"],
        "country": ev["country"],
        "admin": ev["admin"],
        "is_glof": ev["is_glof"],
        "negative_control_note": ev.get("negative_control_note"),
        "n_documents": ev["n_documents"],
        "n_passages": len(passages),
        "distinct_publishers": publishers,
        "n_distinct_publishers": len(publishers),
        "meets_three_source_minimum": len(publishers) >= 3,
        "passages": passages,
    }


def retrieve_all(docs_root, cfg) -> dict:
    manifest = read_json(docs_root / "MANIFEST.json")
    events = {eid: retrieve_event(eid, docs_root, cfg)
              for eid in sorted(manifest["events"])}
    return {"events": events,
            "n_events": len(events),
            "all_meet_three_source_minimum": all(
                e["meets_three_source_minimum"] for e in events.values())}
