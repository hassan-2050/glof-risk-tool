"""Reconcile predicted flood corridors against what the floods actually did.

    python tools/validate_routing.py   ->  outputs/tools/routing_validation.json

WHY THIS EXISTS
---------------
The project validated lake AREA on eight lakes and called that "delineation
validation". It never once checked the other half of the pipeline - the routed
corridor, the part that answers "if this lake goes, where does the water reach
and what does it hit". That is the output a district officer would actually act
on, and it had no error bar at all.

This compares Stage 6's predicted runout against published post-event
observations in data/labels/observed_impacts.json.

WHAT IT IS NOT
--------------
Not a flood model and not a skill score. Runout distance is one scalar per
event, and four events is not a sample. It is the difference between "we have
never checked" and "we have checked four times and here is how far off we were",
which is the only honest basis for deciding whether the corridors are usable.

A tool, not a stage: it reads a committed label file and the run's artefacts,
writes one JSON, and no stage consumes it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import REPO_ROOT  # noqa: E402
from src.common.io import TOOL_OUTPUT_DIR, read_json, write_json  # noqa: E402

OUT = REPO_ROOT / "outputs"
# Tool artefacts live outside the hashed manifest; see
# src.common.io.TOOL_OUTPUT_DIR for why.
SITE = OUT / TOOL_OUTPUT_DIR


def _observed_reach_km(rec: dict) -> tuple[float | None, str]:
    """The distance the flood is known to have reached, and what defines it.

    Prefers the nearest CONFIRMED impact over the maximum debris trace: a
    corridor that reaches the first destroyed asset is doing the job, whereas
    fine sediment carried 169 km is a different quantity and would flatter or
    damn the model depending which you pick. Both are reported.
    """
    if rec.get("critical_asset_reached_km") is not None:
        return float(rec["critical_asset_reached_km"]), "nearest destroyed asset"
    if rec.get("settlement_reached_km") is not None:
        return float(rec["settlement_reached_km"]), "first settlement hit"
    if rec.get("debris_transport_km") is not None:
        return float(rec["debris_transport_km"]), "debris transport limit"
    return None, "no observation"


def main() -> int:
    obs = read_json(REPO_ROOT / "data" / "labels" / "observed_impacts.json")["events"]
    routing = {r["lake_id"]: r for r in read_json(OUT / "stage06_routing.json")["lakes"]}
    long_path = SITE / "long_routing.json"
    exp_path = SITE / "corridor_exposure.json"
    exposure = ({r["lake_id"]: r for r in read_json(exp_path)["lakes"]}
                if exp_path.exists() else {})
    long = ({r["lake_id"]: r for r in read_json(long_path)["lakes"]}
            if long_path.exists() else {})

    rows, ratios = [], []
    for lake_id, rec in sorted(obs.items()):
        r = routing.get(lake_id)
        if r is None:
            continue
        regimes = r.get("regimes") or {}
        # Best case for the model: whichever regime runs furthest.
        pred_m, regime = 0.0, None
        for name, v in regimes.items():
            if (v.get("max_runout_m") or 0) > pred_m:
                pred_m, regime = float(v["max_runout_m"]), name
        truncated = any(v.get("truncated_at_window_edge") for v in regimes.values())

        obs_km, obs_basis = _observed_reach_km(rec)
        near_km = pred_m / 1000.0
        # Prefer the long-domain result where one exists: the near-field figure
        # is capped by a 7 km window and is not a prediction of reach at all.
        lrec = long.get(lake_id)
        # The two regimes BRACKET the answer rather than predicting it: an
        # 11 deg debris rule stops early, a 3 deg clear-water rule runs far, and
        # the truth is between them. Scoring the midpoint would invent a
        # precision the method does not have, so the bracket is the prediction
        # and the test is whether the observation falls inside it.
        lo_km = hi_km = long_km = None
        if lrec:
            runs = {k: v["max_runout_m"] / 1000.0
                    for k, v in lrec["regimes"].items()}
            lo_km = min(runs.values())
            hi_km = max(runs.values())
            long_km = hi_km
        pred_km = long_km if long_km else near_km
        domain = "long (100 km, 90 m)" if long_km else "stage 6 (7 km, 10 m)"
        row = {
            "lake_id": lake_id,
            "event": rec["event"],
            "is_glof": "NEGATIVE CONTROL" not in rec["event"],
            "predicted_runout_km": round(pred_km, 2),
            "predicted_domain": domain,
            "stage6_runout_km": round(near_km, 2),
            "long_runout_km": round(long_km, 2) if long_km else None,
            "bracket_km": ([round(lo_km, 2), round(hi_km, 2)]
                           if lo_km is not None else None),
            "predicted_regime": regime,
            "corridor_truncated_at_window_edge": bool(truncated),
            "observed_reach_km": obs_km,
            "observed_reach_basis": obs_basis,
            "observed_debris_transport_km": rec.get("debris_transport_km"),
        }
        if obs_km and pred_km > 0:
            row["shortfall_factor"] = round(obs_km / pred_km, 1)
            inside = lo_km is not None and lo_km <= obs_km <= hi_km
            row["observation_inside_bracket"] = bool(inside)
            row["bracket_width_factor"] = (round(hi_km / lo_km, 1)
                                           if lo_km else None)
            row["verdict"] = (
                "observation falls inside the debris/clear-water bracket"
                if inside else
                "observation falls OUTSIDE the bracket "
                + ("(further than clear-water reach)" if obs_km > (hi_km or 0)
                   else "(closer than the debris-flow limit)"))
            ratios.append(obs_km / pred_km)
        else:
            row["shortfall_factor"] = None
            row["verdict"] = "not comparable"
        # The sharpest test available: does the corridor pass the place that
        # was actually destroyed, and at roughly the right distance? "Ran far
        # enough" can be satisfied by a corridor down the wrong valley; naming
        # the settlement cannot.
        hits = []
        listed = (exposure.get(lake_id) or {}).get("named_assets") or []
        for want in rec.get("impacted_places", []):
            # Match across scripts. OSM tags Nepali and Chinese places in their
            # own writing systems, so a Latin-only ground truth reports a MISS
            # for a place the corridor did find - Rasuwagadhi is tagged
            # रसुवागढी and was scored as missed until the aliases existed.
            names = [want["name"]] + list(want.get("aliases") or [])
            targets = [n.casefold() for n in names]
            match = next((a for a in listed
                          if any(tg in a["name"].casefold()
                                 or a["name"].casefold() in tg
                                 for tg in targets)), None)
            want_km = want["along_channel_km"]
            got_km = match["along_channel_km"] if match else None
            # Naming the place is necessary but not sufficient: a corridor that
            # meanders can list the right village at the wrong distance, which
            # is a different kind of wrong from missing it. Both are reported.
            ratio = (max(got_km, want_km) / max(min(got_km, want_km), 1e-6)
                     if got_km else None)
            hits.append({
                "place": want["name"],
                "observed_km": want_km,
                "found_in_corridor": bool(match),
                "predicted_km": got_km,
                "distance_ratio": round(ratio, 1) if ratio else None,
                "distance_agrees_within_2x": bool(ratio and ratio <= 2.0),
                "offset_from_channel_m": match["offset_m"] if match else None,
                "what_happened": want["what_happened"],
            })
        if hits:
            row["impacted_places"] = hits
            row["n_places_found"] = sum(1 for x in hits if x["found_in_corridor"])
            row["n_places_found_at_right_distance"] = sum(
                1 for x in hits if x["distance_agrees_within_2x"])
            row["n_places_expected"] = len(hits)
        rows.append(row)

    reached = sum(1 for r in rows if r.get("observation_inside_bracket"))
    found = sum(r.get("n_places_found", 0) for r in rows)
    right = sum(r.get("n_places_found_at_right_distance", 0) for r in rows)
    expected = sum(r.get("n_places_expected", 0) for r in rows)
    comparable = [r for r in rows if r["shortfall_factor"] is not None]
    result = {
        "n_events_with_observations": len(rows),
        "n_comparable": len(comparable),
        "n_corridors_reaching_observed_impact": reached,
        "shortfall_factor_min": round(min(ratios), 1) if ratios else None,
        "shortfall_factor_max": round(max(ratios), 1) if ratios else None,
        "per_event": rows,
        "n_impacted_places_found": found,
        "n_impacted_places_found_at_right_distance": right,
        "n_impacted_places_expected": expected,
        "headline": (
            f"{reached} of {len(comparable)} observed reaches fall inside the "
            f"predicted debris/clear-water bracket; the corridor passes "
            f"{found} of {expected} settlements the floods are documented to "
            f"have destroyed, {right} of them at a distance within 2x of the "
            f"observed one."),
        "bracket_caveat": (
            "The bracket is wide - often two orders of magnitude - because a "
            "reach-angle rule on a 90 m DEM with no hydraulics cannot do "
            "better. Containing the answer is not the same as predicting it, "
            "and a bracket this wide is a screening statement, not a forecast."),
        "diagnosis": (
            "The shortfall is the ANALYSIS DOMAIN, not the routing rule. Every "
            "lake sits in a 7 km window (3.5 km half-width), so no corridor can "
            "exceed ~3.5 km from the lake however the physics behaves, and "
            "several terminate at the window edge with the flag set. Observed "
            "reaches are 10-169 km. Until the domain follows the river network "
            "instead of a box around the lake, corridor runout is a LOWER BOUND "
            "and must not be read as an inundation extent."),
        "what_this_does_not_test": (
            "Corridor WIDTH, depth, arrival time, and everything downstream of "
            "the window edge. A corridor that reached the right distance could "
            "still be in the wrong valley; only the reach is checked here."),
    }
    SITE.mkdir(parents=True, exist_ok=True)
    write_json(SITE / "routing_validation.json", result)

    w = max(len(r["lake_id"]) for r in rows) + 2
    print(f"{'lake':<{w}}{'stage 6':>10}{'long':>10}{'observed':>10}"
          f"{'short by':>10}  basis")
    for r in rows:
        sf = f"{r['shortfall_factor']}x" if r["shortfall_factor"] else "-"
        ob = f"{r['observed_reach_km']:g} km" if r["observed_reach_km"] else "-"
        lg = f"{r['long_runout_km']:.2f} km" if r["long_runout_km"] else "-"
        print(f"{r['lake_id']:<{w}}{r['stage6_runout_km']:>7.2f} km{lg:>10}{ob:>10}"
              f"{sf:>10}  {r['observed_reach_basis']}")
    print(f"\n{result['headline']}")
    print("\nnamed places the floods actually destroyed:")
    for r in rows:
        for hp in r.get("impacted_places", []):
            mark = ("FOUND " if hp["distance_agrees_within_2x"]
                    else "far   " if hp["found_in_corridor"] else "MISSED")
            pk = (f"{hp['predicted_km']:.1f} km"
                  if hp["predicted_km"] is not None else "-")
            print(f"  {mark} {hp['place']:<14} observed {hp['observed_km']:>3} km"
                  f"   corridor {pk:>9}")
    print("-> outputs/tools/routing_validation.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
