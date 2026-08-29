"""Stage 13: CAP 1.2 XML and HXL-tagged CSV, from the same structured data.

Both exports are generated from the reconciliation output that the sitrep is
written from, not re-derived, so the machine-readable and human-readable paths
cannot drift. That is the Stage 13 criterion and it is met structurally rather
than by a later consistency check.

CAP (OASIS Common Alerting Protocol 1.2) is the interchange format emergency
management systems already ingest. Two decisions in the mapping deserve stating:

* `status` is `Exercise`, never `Actual`. This is a research prototype and the
  underlying analysis is a hindcast; emitting `Actual` would put a
  well-formed, machine-ingestible alert into a format designed to be acted on
  automatically. That single attribute is the difference between a
  demonstration and a false alarm in someone's operations centre.

* A contested figure is emitted as a `<parameter>` carrying the RANGE and the
  disagreeing sources, not as a single value. CAP has no native representation
  for "sources disagree", and silently choosing one would discard the finding
  the whole project is built around.

HXL (Humanitarian Exchange Language) tags sit in the row directly beneath the
header, per spec, so the file opens as an ordinary spreadsheet while remaining
machine-parseable.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"

# Quantity -> HXL hashtag. HXL's core vocabulary is small, so several of these
# use #meta +name attributes rather than inventing tags.
HXL_TAGS = {
    "event_id": "#meta +id",
    "event_title": "#event +name",
    "country": "#country +name",
    "admin": "#adm1 +name",
    "hazard_type": "#event +type",
    "quantity": "#indicator +name",
    "value_min": "#indicator +num +min",
    "value_max": "#indicator +num +max",
    "contested": "#meta +contested",
    "severity": "#severity +code",
    "n_sources": "#meta +num +sources",
    "publishers": "#meta +source",
    "as_of": "#date +reported",
}


def build_cap(event: dict, recon: dict, draft: dict, cfg) -> ET.Element:
    ident = f"glof-risk-tool.{event['event_id']}"
    alert = ET.Element("alert", xmlns=CAP_NS)
    ET.SubElement(alert, "identifier").text = ident
    ET.SubElement(alert, "sender").text = cfg.require("reporter.cap.sender")
    ET.SubElement(alert, "sent").text = cfg.require("reporter.cap.sent_timestamp")
    # Exercise, not Actual. See the module docstring - this is the attribute
    # that keeps a demonstration out of an operations centre.
    ET.SubElement(alert, "status").text = "Exercise"
    ET.SubElement(alert, "msgType").text = "Alert"
    ET.SubElement(alert, "scope").text = "Public"
    ET.SubElement(alert, "note").text = (
        "RESEARCH PROTOTYPE - hindcast analysis, not an operational warning. "
        "Decision-support for DHM, NDRRMA and ICIMOD, who hold the mandate.")

    info = ET.SubElement(alert, "info")
    ET.SubElement(info, "language").text = "en-GB"
    ET.SubElement(info, "category").text = "Geo"
    ET.SubElement(info, "event").text = (
        "Glacial Lake Outburst Flood" if event["is_glof"]
        else "Rock and Ice Avalanche / Debris Flow")
    ET.SubElement(info, "urgency").text = "Past"
    ET.SubElement(info, "severity").text = "Severe"
    ET.SubElement(info, "certainty").text = (
        "Observed" if event["is_glof"] else "Observed")
    ET.SubElement(info, "senderName").text = cfg.require("reporter.cap.sender_name")
    ET.SubElement(info, "headline").text = event["title"][:160]
    ET.SubElement(info, "description").text = " ".join(
        draft["sections"]["situation_overview"])[:1800]
    ET.SubElement(info, "instruction").text = (
        "Verify all figures with DHM / NDRRMA before operational use. "
        "Figures marked contested differ across sources and no single value "
        "has been adopted.")

    if not event["is_glof"]:
        # The negative control must carry its correction in the machine-readable
        # output too, not only in the prose a human reads.
        p = ET.SubElement(info, "parameter")
        ET.SubElement(p, "valueName").text = "classification_correction"
        ET.SubElement(p, "value").text = (
            "NOT a glacial lake outburst flood. Peer-reviewed analysis "
            "attributes this event to a rock and ice avalanche with no lake "
            "involved (Shugar et al. 2021, Science).")

    for c in recon["contradictions"]:
        p = ET.SubElement(info, "parameter")
        ET.SubElement(p, "valueName").text = f"contested:{c['quantity']}"
        if "stated_total" in c:
            val = (f"document states {c['stated_total']:g} but its own items sum "
                   f"to {c['itemised_sum']:g} ({c['publisher']})")
        else:
            pubs = sorted({v["publisher"] for v in c["values"]})
            val = (f"{c['min']:g} to {c['max']:g} across {len(pubs)} sources "
                   f"({'; '.join(pubs)})")
        ET.SubElement(p, "value").text = val

    area = ET.SubElement(info, "area")
    ET.SubElement(area, "areaDesc").text = f"{event['admin']}, {event['country']}"
    return alert


def cap_to_string(alert: ET.Element) -> str:
    ET.indent(alert, space="  ")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(alert, encoding="unicode") + "\n")


def validate_cap(alert: ET.Element) -> dict:
    """Structural conformance check against CAP 1.2's required elements.

    Not a full XSD validation - that would need the OASIS schema as a network
    or vendored dependency. This checks the mandatory element set and the
    controlled vocabularies, which is what actually goes wrong in practice, and
    says plainly that it is not schema validation rather than implying it is.
    """
    required_alert = ["identifier", "sender", "sent", "status", "msgType", "scope"]
    required_info = ["category", "event", "urgency", "severity", "certainty"]
    vocab = {
        "status": {"Actual", "Exercise", "System", "Test", "Draft"},
        "msgType": {"Alert", "Update", "Cancel", "Ack", "Error"},
        "scope": {"Public", "Restricted", "Private"},
        "urgency": {"Immediate", "Expected", "Future", "Past", "Unknown"},
        "severity": {"Extreme", "Severe", "Moderate", "Minor", "Unknown"},
        "certainty": {"Observed", "Likely", "Possible", "Unlikely", "Unknown"},
    }
    problems = []
    for tag in required_alert:
        if alert.find(tag) is None:
            problems.append(f"alert missing required element <{tag}>")
    info = alert.find("info")
    if info is None:
        problems.append("alert missing required <info> block")
    else:
        for tag in required_info:
            if info.find(tag) is None:
                problems.append(f"info missing required element <{tag}>")
    for parent, tag in [(alert, "status"), (alert, "msgType"), (alert, "scope"),
                        (info, "urgency"), (info, "severity"), (info, "certainty")]:
        if parent is None:
            continue
        el = parent.find(tag)
        if el is not None and el.text not in vocab[tag]:
            problems.append(f"<{tag}> value {el.text!r} is not in the CAP 1.2 "
                            f"controlled vocabulary")
    return {"valid": not problems, "problems": problems,
            "method": ("required-element and controlled-vocabulary check against "
                       "the CAP 1.2 specification; NOT full XSD schema "
                       "validation, which would require the OASIS schema as a "
                       "vendored or network dependency")}


def build_hxl_rows(event: dict, recon: dict, as_of: str) -> list[dict]:
    rows = []
    base = {"event_id": event["event_id"], "event_title": event["title"],
            "country": event["country"], "admin": event["admin"],
            "hazard_type": "GLOF" if event["is_glof"] else "rock_ice_avalanche",
            "as_of": as_of}
    for c in recon["contradictions"]:
        if "stated_total" in c:
            lo = hi = c["stated_total"]
            pubs = [c["publisher"]]
        else:
            lo, hi = c["min"], c["max"]
            pubs = sorted({v["publisher"] for v in c["values"]})
        rows.append({**base, "quantity": c["quantity"],
                     "value_min": lo, "value_max": hi,
                     "contested": "yes", "severity": c["severity"],
                     "n_sources": len(pubs), "publishers": "; ".join(pubs)})
    # Uncontested figures, so the export is the full picture rather than only
    # the disagreements.
    by_q: dict[str, list[dict]] = {}
    for cl in recon["claims"]:
        by_q.setdefault(cl["quantity"], []).append(cl)
    contested_q = {c["quantity"] for c in recon["contradictions"]}
    for q, group in sorted(by_q.items()):
        if q in contested_q:
            continue
        vals = {g["normalised_value"] for g in group}
        if len(vals) != 1:
            continue
        v = next(iter(vals))
        pubs = sorted({g["publisher"] for g in group})
        rows.append({**base, "quantity": q, "value_min": v, "value_max": v,
                     "contested": "no", "severity": "",
                     "n_sources": len(pubs), "publishers": "; ".join(pubs)})
    return rows
