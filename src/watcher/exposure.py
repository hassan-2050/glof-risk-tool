"""Stage 5: who and what lies in the indicative corridor.

This is what turns a geometry exercise into decision support. A hazard ranking
without exposure tells an officer which lake is interesting; a hazard ranking
with exposure tells them which valley to visit.

Two independent estimates, on purpose:

  OSM         counts actual mapped features and, crucially, says WHAT they are.
              A hydropower plant and a shed are both "a building" to a gridded
              product; only OSM distinguishes them, and that distinction is the
              whole Nepal exposure story - 405 MW plus a 25 MW solar plant at
              Rasuwa, Teesta III's 1,200 MW at Sikkim.
  WorldPop    a 100 m modelled population grid, entirely different method.

Where both exist and disagree materially, the divergence is REPORTED rather
than resolved. Two products disagreeing by a factor of three is information
about confidence; picking the larger one and moving on is not.

Coverage is asymmetric and the output says so per lake: WorldPop is pinned for
Nepal only, because the India and China rasters are 506 MB and 657 MB and the
server ignores HTTP Range requests. South Lhonak, Chamoli and Pyurepu therefore
carry an OSM-only estimate, explicitly flagged, rather than a silent zero that
would read as "nobody lives there".
"""
from __future__ import annotations

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.warp import Resampling as WarpResampling
from rasterio.warp import reproject

# Persons per building, applied to OSM residential footprints. The value is
# from a documented Nepal gridded-population method; it is a crude multiplier
# and is tagged as such wherever it is used.
PERSONS_PER_BUILDING = 9.6

# Weights expressing that not all exposure is equal. A health post lost in a
# flood removes the response capacity as well as the asset, so it outranks an
# equal number of ordinary buildings. These are OUR judgement, not a published
# scheme, and are reported alongside the raw counts so a reviewer can reweight.
CRITICALITY = {
    "hydropower": 10.0,
    "power_substation": 6.0,
    "health_post": 8.0,
    "school": 6.0,
    "bridge": 4.0,
    "settlement": 5.0,
    "road": 1.0,
    "building": 1.0,
}


def classify(el: dict) -> str | None:
    """Map an OSM element to one of our reportable exposure classes.

    Lives HERE, on the offline side, not in the fetcher. Stage 5 imported it
    from src.data.fetch_exposure and the offline guard killed the run: that
    module imports requests, which imports ssl, which the guard has patched.
    The guard was right - the reproduce path must not touch the network module
    at all - so the shared logic moved to where both callers can reach it
    without dragging a network stack onto the reproduce path.
    """
    t = el.get("tags", {})
    if t.get("power") in ("plant", "generator") or t.get("waterway") in ("dam", "weir"):
        return "hydropower"
    if t.get("power") == "substation":
        return "power_substation"
    if t.get("amenity") in ("school", "college", "kindergarten"):
        return "school"
    if t.get("amenity") in ("hospital", "clinic", "doctors", "pharmacy"):
        return "health_post"
    if t.get("bridge") and t.get("bridge") != "no":
        return "bridge"
    if t.get("highway"):
        return "road"
    if t.get("place"):
        return "settlement"
    if t.get("building"):
        return "building"
    return None


def elements_in_corridor(osm: dict, corridor: np.ndarray, transform, crs,
                         classify) -> dict:
    """Count OSM features whose centre falls inside the corridor."""
    tf = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    inv = ~transform
    h, w = corridor.shape
    counts: dict[str, int] = {}
    named: list[dict] = []

    for el in osm.get("elements", []):
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            continue
        cls = classify(el)
        if cls is None:
            continue
        x, y = tf.transform(lon, lat)
        col, row = inv * (x, y)
        r, c = int(row), int(col)
        if not (0 <= r < h and 0 <= c < w) or not corridor[r, c]:
            continue
        counts[cls] = counts.get(cls, 0) + 1
        tags = el.get("tags", {})
        if cls in ("hydropower", "power_substation", "health_post", "school",
                   "settlement") and tags.get("name"):
            named.append({"class": cls, "name": tags["name"],
                          "osm_type": el.get("type"), "osm_id": el.get("id"),
                          "tags": {k: v for k, v in tags.items()
                                   if k in ("name", "power", "amenity", "place",
                                            "plant:output:electricity")}})
    return {"counts": counts, "named_assets": sorted(
        named, key=lambda a: (a["class"], a["name"]))}


def worldpop_in_corridor(path, corridor: np.ndarray, transform, crs) -> dict | None:
    """Sum the WorldPop grid over the corridor, warped onto the scene grid."""
    try:
        dst = np.full(corridor.shape, np.nan, dtype="float32")
        with rasterio.open(path) as src:
            reproject(source=rasterio.band(src, 1), destination=dst,
                      src_transform=src.transform, src_crs=src.crs,
                      dst_transform=transform, dst_crs=crs,
                      resampling=WarpResampling.bilinear,
                      src_nodata=src.nodata, dst_nodata=np.nan)
    except Exception:  # noqa: BLE001
        return None
    vals = dst[corridor]
    vals = vals[np.isfinite(vals)]
    if not vals.size:
        # NOT a failure. WorldPop "constrained" assigns population only where
        # buildings exist, so an uninhabited glacier basin is legitimately
        # nodata throughout. A direct window read over Tsho Rolpa returns 6,460
        # nodata cells and zero valid ones. Reporting this as a null would be
        # indistinguishable from a broken overlay, so it is reported as a
        # measured zero with its reason.
        return {"population": 0.0, "cells": 0, "all_nodata": True,
                "note": ("WorldPop constrained has no populated cells anywhere in "
                         "this corridor. The product only assigns population where "
                         "buildings are detected, so this is a measured absence of "
                         "settlement, not a coverage gap or an overlay failure.")}
    # WorldPop cells are 100 m; the scene grid is 10 m, so a straight sum over
    # warped cells would count each person ~100 times.
    scale = (10.0 / 100.0) ** 2
    return {"population": round(float(vals.sum() * scale), 1),
            "cells": int(vals.size),
            "note": ("bilinear warp from the 100 m WorldPop grid onto the 10 m "
                     "scene grid, rescaled by cell-area ratio")}


def assess(lake: dict, osm: dict, corridor: np.ndarray, transform, crs,
           worldpop_path, classify) -> dict:
    inside = elements_in_corridor(osm, corridor, transform, crs, classify)
    counts = inside["counts"]

    osm_pop = counts.get("building", 0) * PERSONS_PER_BUILDING
    wp = None
    if worldpop_path is not None and lake.get("country") == "NP":
        wp = worldpop_in_corridor(worldpop_path, corridor, transform, crs)

    divergence = None
    if wp and osm_pop > 0 and wp["population"] > 0:
        hi, lo = max(osm_pop, wp["population"]), min(osm_pop, wp["population"])
        pct = 100.0 * (hi - lo) / lo
        divergence = {
            "osm_derived": round(osm_pop, 1),
            "worldpop": wp["population"],
            "difference_pct": round(pct, 1),
            "materially_different": pct >= 25.0,
            "interpretation": (
                "Two independent methods disagree by more than a quarter. Both "
                "figures are reported; neither is adopted, and the range is what "
                "should inform planning."
                if pct >= 25.0 else
                "Both methods agree within a quarter, which raises confidence in "
                "the order of magnitude."),
        }

    critical = {k: v for k, v in counts.items()
                if k in ("hydropower", "power_substation", "health_post",
                         "school", "bridge")}
    score = sum(CRITICALITY.get(k, 1.0) * v for k, v in counts.items())

    return {
        "lake_id": lake["id"],
        "country": lake["country"],
        "counts": counts,
        # Reported as its own field, never folded into a generic asset blob:
        # hydropower is the headline exposure story for Nepal GLOFs.
        "critical_infrastructure": critical,
        "hydropower_in_corridor": counts.get("hydropower", 0),
        "named_assets": inside["named_assets"],
        "population": {
            "osm_derived": round(osm_pop, 1),
            "osm_method": f"{counts.get('building', 0)} buildings x "
                          f"{PERSONS_PER_BUILDING} persons/building (documented "
                          f"Nepal method; crude)",
            "worldpop": wp,
            "worldpop_available": wp is not None,
            "worldpop_unavailable_reason": (
                None if wp is not None else
                "WorldPop pinned for Nepal only; India and China rasters are "
                "506 MB and 657 MB and the server ignores HTTP Range requests. "
                "This is a coverage gap, NOT an absence of population."),
            "divergence": divergence,
        },
        "criticality_weighted_score": round(score, 1),
        "criticality_weights": CRITICALITY,
        "weights_note": ("our judgement, not a published scheme; raw counts are "
                         "reported alongside so a reviewer can reweight"),
    }
