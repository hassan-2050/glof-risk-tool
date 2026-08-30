"""Per-lake outburst scenarios: volume in, corridor and assets out.

    python tools/build_scenarios.py    -> outputs/tools/scenarios.json
                                          outputs/tools/scenarios.md

Assembles the pieces the pipeline already produces into the statement a duty
officer would actually read:

    "If <lake> releases <volume band>, the flow follows the <river> for
     <bracket> km and passes <places>, the nearest being <place> at <km>."

EVERY QUANTITY HERE IS A RANGE, AND THAT IS THE POINT
-----------------------------------------------------
  * volume comes from an area-depth relation with 50 to >400% error
    (Cook & Quincey 2015), so it is a band, never a point
  * reach comes from two reach-angle regimes that BRACKET the answer - an
    11 deg debris rule and a 3 deg clear-water rule - and on the four hindcast
    events that bracket is often two orders of magnitude wide
  * assets are listed by POSITION along the channel, not by inundation: there
    is no depth, no discharge and no hydraulics anywhere in this chain

Collapsing any of those to a single number would make the output look like a
forecast. It is a screening triage list, and the wording is chosen so it cannot
be read as anything else.

TIMING IS ABSENT ON PURPOSE. Nothing here predicts WHEN a lake releases; the
trigger is an avalanche nobody observes in advance.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import REPO_ROOT, load_config                 # noqa: E402
from src.common.io import (TOOL_OUTPUT_DIR, read_json,               # noqa: E402
                           write_json, write_text)
from src.watcher.proxies import volume_band                          # noqa: E402

OUT = REPO_ROOT / "outputs"
SITE = OUT / TOOL_OUTPUT_DIR

# Classes worth naming individually in a triage line.
HEADLINE_CLASSES = ["settlement", "hydropower", "substation", "school",
                    "health", "bridge"]

# Explicit plurals. Appending "s" produced "5 healths" and "4 hydropowers" in a
# document meant for someone deciding where to send a survey team.
PLURAL = {
    "settlement": ("settlement", "settlements"),
    "hydropower": ("hydropower plant", "hydropower plants"),
    "substation": ("substation", "substations"),
    "school": ("school", "schools"),
    "health": ("health facility", "health facilities"),
    "bridge": ("bridge", "bridges"),
    "road": ("major road", "major roads"),
    "building": ("building", "buildings"),
}


def capacity_trend(traj: dict, cfg) -> dict | None:
    """Where the release band goes if the MEASURED trend continues.

    Capacity forecast, NOT hazard forecast - and the difference is the
    project's whole thesis. Thame was stable in area and burst anyway, so an
    area trend must never be read as risk going up or down. What the trend
    does set is how much water is available on the day a trigger arrives, and
    that this tool can project honestly: the Theil-Sen slope Stage 3 already
    fits (robust to the QA-rejected scenes), pushed 12 months past the last
    measurement and fed through the SAME two area-volume relations as the
    current band. Both bands carry the same 50 to >400% error; what is new
    information is only the difference between them.
    """
    tr = (traj or {}).get("trend") or {}
    if not tr.get("sufficient"):
        return None
    slope = tr.get("theil_sen_slope_m2_per_year")
    last = tr.get("last_area_m2")
    if slope is None or not last:
        return None
    area_next = max(0.0, last + slope)
    now = volume_band(last, cfg)["value"] or {}
    nxt = volume_band(area_next, cfg)["value"] or {}
    return {
        "basis": (f"Theil-Sen slope over {tr['n_annual_observations']} annual "
                  f"observations, {tr['span_years']} yr span"),
        "slope_m2_per_year": slope,
        "slope_mad_m2_per_year": tr.get("theil_sen_slope_mad"),
        "last_measured": {"date": tr.get("last_date"), "area_m2": last},
        "area_in_12mo_m2": round(area_next, 0),
        "band_now_m3": now,
        "band_in_12mo_m3": nxt,
        "delta_central_m3": round((nxt.get("central_m3") or 0)
                                  - (now.get("central_m3") or 0), 0),
        "caveat": ("Capacity forecast, not hazard forecast. Thame was stable "
                   "in area and burst anyway; the trend only sets how much "
                   "water is waiting when a trigger arrives. Same 50 to "
                   ">400% volume error as the current band."),
    }


def _fmt_m3(v: float | None) -> str:
    if not v:
        return "unknown"
    if v >= 1e6:
        return f"{v / 1e6:.1f} million m3"
    return f"{v:,.0f} m3"


def main() -> int:
    lakes = {l["id"]: l for l in
             read_json(REPO_ROOT / "data" / "labels" / "lakes.json")["lakes"]}
    proxies = {r["lake_id"]: r for r in
               read_json(OUT / "stage04_proxies.json")["lakes"]}
    weval = read_json(OUT / "stage07_watcher_eval.json")["per_lake"]
    cfg = load_config()
    traj = {r["lake_id"]: r for r in
            read_json(OUT / "stage03_trajectory.json")["lakes"]}
    long = {r["lake_id"]: r for r in read_json(SITE / "long_routing.json")["lakes"]}
    exp_path = SITE / "corridor_exposure.json"
    exposure = ({r["lake_id"]: r for r in read_json(exp_path)["lakes"]}
                if exp_path.exists() else {})

    scenarios = []
    for lid, rec in sorted(long.items()):
        lake = lakes.get(lid, {})
        px = {p["proxy"]: p for p in (proxies.get(lid) or {}).get("proxies", [])}
        band = (px.get("volume_band") or {}).get("value") or {}
        ev = weval.get(lid, {})

        runs = {k: v["max_runout_m"] / 1000.0 for k, v in rec["regimes"].items()}
        lo, hi = min(runs.values()), max(runs.values())
        truncated = any(v.get("truncated_at_domain_edge")
                        for v in rec["regimes"].values())

        exr = exposure.get(lid) or {}
        # A lake Overpass never answered for has no counts, and an empty count
        # dict renders identically to "nothing is downstream". Carry the
        # distinction through instead of letting it collapse here. A record
        # written before the flag existed was, by definition, queried.
        osm_ok = bool(exr) and exr.get("osm_available", True)
        osm_why = exr.get("osm_error") or "no OpenStreetMap extract"
        counts = exr.get("counts") or {}
        named = exr.get("named_assets") or []
        settlements = [a for a in named if a["class"] == "settlement"]
        nearest = settlements[0] if settlements else (named[0] if named else None)

        scenarios.append({
            "lake_id": lid,
            "name": lake.get("name", lid),
            "basin": lake.get("basin"),
            "screening": {
                "source_to_lake_volume_ratio": ev.get("proxy_augmented", {}).get("score"),
                "rank_note": "see stage07 ranking; 1 is most exposed",
                "flagged": ev.get("proxy_augmented", {}).get("flagged"),
            },
            "release_volume_band_m3": {
                "low": band.get("low_m3"), "central": band.get("central_m3"),
                "high": band.get("high_m3"),
                "caveat": "area-depth relation, 50 to >400% error "
                          "(Cook & Quincey 2015)",
            },
            "reach_km": {
                "debris_flow_11deg": round(runs.get("debris_flow", 0.0), 1),
                "clearwater_3deg": round(runs.get("clearwater_flood", 0.0), 1),
                "bracket": [round(lo, 1), round(hi, 1)],
                "bracket_width_factor": round(hi / lo, 1) if lo else None,
                "truncated_at_domain_edge": truncated,
                "caveat": "a bracket, not a prediction; the two regimes are the "
                          "physical bounds and the truth lies between them",
            },
            "capacity_trend": capacity_trend(traj.get(lid), cfg),
            "assets_along_corridor": {
                "osm_available": osm_ok,
                "osm_unavailable_reason": None if osm_ok else osm_why,
                "counts": counts,
                "population": exr.get("population_in_corridor"),
                "n_named": len(named),
                "nearest_named": nearest,
                "first_five": named[:5],
                "caveat": "position within 500 m of the routed channel; not an "
                          "inundation call",
            },
        })

    write_json(SITE / "scenarios.json", {"lakes": scenarios})

    lines = ["# Outburst scenarios", "",
             "One block per lake with a routed corridor. Every figure is a "
             "range. Nothing here predicts *when*.", ""]
    for s in scenarios:
        r, a = s["reach_km"], s["assets_along_corridor"]
        v = s["release_volume_band_m3"]
        lines += [f"## {s['name']}", ""]
        lines.append(
            f"- **If it releases** {_fmt_m3(v['central'])} "
            f"(range {_fmt_m3(v['low'])} to {_fmt_m3(v['high'])})")
        lines.append(
            f"- **Flow reaches** between **{r['bracket'][0]} km** (debris flow, "
            f"11 deg) and **{r['bracket'][1]} km** (clear water, 3 deg) down the "
            f"{s['basin'] or 'valley'}"
            + ("  \n  *corridor leaves the 100 km analysis domain, so the upper "
               "figure is a lower bound*" if r["truncated_at_domain_edge"] else ""))
        if not a["osm_available"]:
            lines.append("- **In the corridor:** not queried - "
                         f"{a['osm_unavailable_reason']}. That is a missing "
                         "answer, not an empty one.")
        elif a["counts"]:
            got = ", ".join(
                f"{n} {PLURAL.get(k, (k, k + 's'))[0 if n == 1 else 1]}"
                for k, n in sorted(a["counts"].items())
                if k in HEADLINE_CLASSES)
            lines.append(f"- **In the corridor:** {got}")
        pop = a.get("population") or {}
        if pop.get("available") and pop.get("zero_note"):
            # Never print a bare "~0 people". The zero is true of the 500 m
            # band and false of the valley, and only the second reading is the
            # one a reader acts on.
            near = pop.get("nearest_populated_cell_m")
            lines.append(
                "- **People in the corridor:** none within 500 m of the channel"
                + ("" if near is None else
                   f", but ~{pop['population_within_2km']:,.0f} within 2 km "
                   f"(nearest populated cell {near:,.0f} m away)")
                + "  \n  *WorldPop places people on detected building "
                  "footprints, which sit on the valley shoulder more often "
                  "than on the channel; this is not an empty valley*")
        elif pop.get("available"):
            cov = pop["coverage_fraction"]
            # Coverage is stated whenever the corridor leaves Nepal. WorldPop's
            # Nepal raster has no cells over Tibet or India, and an uncovered
            # cell is not an empty one - reporting the sum without the fraction
            # would understate a transboundary corridor without saying so.
            partial = ("  \n  *only {:.0%} of the corridor lies inside the "
                       "Nepal raster; the rest is uncovered, not empty*"
                       ).format(cov) if cov < 0.98 else ""
            lines.append(
                f"- **People in the corridor:** ~{pop['population']:,.0f} "
                f"(WorldPop 2020, 100 m, within 500 m of the channel)"
                + partial)
        if not pop.get("available") and pop.get("reason"):
            lines.append(f"- **People in the corridor:** not measured - "
                         f"{pop['reason']}. Absent, not zero.")
        ct = s.get("capacity_trend")
        if ct and abs(ct["slope_m2_per_year"]) >= 1000:
            growing = ct["slope_m2_per_year"] > 0
            nb = ct["band_in_12mo_m3"]
            lines.append(
                f"- **If the measured trend holds** ({ct['slope_m2_per_year']:+,.0f} "
                f"m²/yr, {ct['basis']}), the release band 12 months after "
                f"{ct['last_measured']['date']} is {_fmt_m3(nb.get('low_m3'))} to "
                f"{_fmt_m3(nb.get('high_m3'))}"
                + ("" if growing else " — stable or shrinking")
                + "  \n  *capacity forecast, not hazard forecast: Thame was "
                  "stable in area and burst anyway; the trend only sets how "
                  "much water is waiting when a trigger arrives*")
        if a["nearest_named"]:
            nn = a["nearest_named"]
            lines.append(f"- **Nearest named place:** {nn['name']} "
                         f"at {nn['along_channel_km']} km "
                         f"({nn['offset_m']} m from the channel)")
        if a["first_five"]:
            seq = " -> ".join(f"{x['name']} ({x['along_channel_km']} km)"
                              for x in a["first_five"])
            lines.append(f"- **Downstream order:** {seq}")
        lines.append("")
    lines += ["---", "",
              "**Read this before quoting any figure above.** Volumes carry 50 "
              "to >400% error. Reaches are a bracket between two reach-angle "
              "regimes, not a prediction, and on the four hindcast events the "
              "observed reach fell inside that bracket 2 times out of 4. Assets "
              "are listed because they sit within 500 m of a routed channel on "
              "a 90 m DEM - there is no depth, no discharge and no hydraulics "
              "in this chain. Nothing here says when.", ""]
    write_text(SITE / "scenarios.md", "\n".join(lines))

    print(f"{len(scenarios)} scenarios -> outputs/tools/scenarios.json + .md")
    for s in scenarios:
        a = s["assets_along_corridor"]
        assets = (f"{sum((a['counts'] or {}).values())} assets, "
                  f"{a['n_named']} named" if a["osm_available"]
                  else "assets NOT QUERIED")
        print(f"  {s['lake_id']:<24} reach {s['reach_km']['bracket']} km, "
              + assets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
