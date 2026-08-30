"""Route every lake with a downstream DEM, over the full 100 km domain.

    python -m src.data.fetch_downstream       # once, needs network
    python tools/run_long_routing.py          # -> outputs/tools/long_routing.json

A tool, not a stage: it depends on dem_downstream.tif, which is fetched
separately and is not part of the committed reproduce set for every lake. Stage
6 remains the reproducible near-field result; this is the long-range answer to
"how far does it go, and past what".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage
from pyproj import Transformer
from rasterio.warp import transform_bounds

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import REPO_ROOT, load_config          # noqa: E402
from src.common.io import (TOOL_OUTPUT_DIR, read_json,        # noqa: E402
                          write_json)
from src.watcher.routing_long import route_long               # noqa: E402

OUT = REPO_ROOT / "outputs"
# Tool artefacts live outside the hashed manifest; see
# src.common.io.TOOL_OUTPUT_DIR for why.
SITE = OUT / TOOL_OUTPUT_DIR

# Vertical tolerance for "this is still the lake surface". GLO-30's
# stated vertical accuracy is ~4 m, so 3 m stays inside the noise while
# still separating water from the moraine that impounds it.
FLAT_TOLERANCE_M = 3.0


def _seed_from_lake(src, lat: float, lon: float, area_m2: float) -> np.ndarray:
    """Mark the lake on the coarse grid as a disc of the right area.

    The 10 m outline is not reprojected: at 90 m a 0.02 km2 lake is two cells,
    so an exact outline would be spurious precision. A disc of equal area,
    centred on the registered coordinate, carries the one property the router
    needs - where the water starts and roughly how wide the outlet front is.
    """
    row, col = src.index(lon, lat)
    seed = np.zeros((src.height, src.width), dtype=bool)
    if not (0 <= row < src.height and 0 <= col < src.width):
        return seed
    res_m = abs(src.transform.a) * 111320.0 * np.cos(np.radians(lat))
    radius_cells = max(0, int(round(((area_m2 / np.pi) ** 0.5) / res_m)))
    rr, cc = np.ogrid[:src.height, :src.width]
    seed[((rr - row) ** 2 + (cc - col) ** 2) <= radius_cells ** 2] = True
    seed[row, col] = True                       # never an empty seed

    # Then grow the seed across the flat water surface.
    #
    # An equal-area DISC is wrong for an elongated lake. South Lhonak is ~2 km
    # long; its equal-area disc is 450 m across, so most of the lake sat OUTSIDE
    # the seed as flat ground at exactly the lake elevation - and the descent
    # walked onto it and stalled, reporting 0.22 km against an observed 60 km.
    # A flood fill over cells within a few metres of the lake surface captures
    # the water body whatever shape it is.
    z = src.read(1).astype(np.float32)
    if src.nodata is not None:
        z[z == src.nodata] = np.nan
    z[z <= 0] = np.nan
    level = float(np.nanmedian(z[seed]))
    flat = np.isfinite(z) & (np.abs(z - level) <= FLAT_TOLERANCE_M)
    lab, _ = ndimage.label(flat)
    here = lab[row, col]
    if here:
        grown = lab == here
        # Guard against a fill that escapes down a flat valley floor: cap it at
        # a few times the lake's own radius.
        cap = max(radius_cells * 4, 8)
        near = ((rr - row) ** 2 + (cc - col) ** 2) <= cap ** 2
        seed |= grown & near
    return seed


def main() -> int:
    cfg = load_config()
    pinned = cfg.path("pinned")
    lakes = {l["id"]: l for l in
             read_json(REPO_ROOT / "data" / "labels" / "lakes.json")["lakes"]}
    delin = {r["lake_id"]: r for r in
             read_json(OUT / "stage02_delineation.json")["lakes"]}
    stage6 = {r["lake_id"]: r for r in
              read_json(OUT / "stage06_routing.json")["lakes"]}

    debris_deg = cfg.require("routing.stop_reach_angle_deg")
    clear_deg = cfg.require("routing.clearwater_reach_angle_deg")
    buffer_m = cfg.require("routing.lateral_buffer_m")

    results = []
    for lid, lake in lakes.items():
        dem_path = pinned / lid / "dem_downstream.tif"
        if not dem_path.exists():
            continue
        best = (delin.get(lid) or {}).get("validation") or {}
        area_m2 = best.get("best_measured_area_m2") or 10000.0

        with rasterio.open(dem_path) as src:
            dem = src.read(1).astype(np.float32)
            nod = src.nodata
            if nod is not None:
                dem[dem == nod] = np.nan
            # These mosaics carry no declared nodata and pad the requested box
            # with a row or column of exact zeros. In a domain whose lowest real
            # ground is 496 m, a 0 m cell is a bottomless sink that any descent
            # falls into and cannot leave.
            dem[dem <= 0] = np.nan
            res_m = abs(src.transform.a) * 111320.0 * float(
                np.cos(np.radians(lake["lat"])))
            seed = _seed_from_lake(src, lake["lat"], lake["lon"], area_m2)
            bounds_wgs = list(src.bounds)
            transform = src.transform

        rec = {"lake_id": lid, "name": lake["name"],
               "dem_resolution_m": round(res_m, 1),
               "domain_bounds_wgs84": [round(b, 6) for b in bounds_wgs],
               "seed_cells": int(seed.sum()), "regimes": {}}
        for regime, angle in (("debris_flow", debris_deg),
                              ("clearwater_flood", clear_deg)):
            r = route_long(dem, seed, res_m, angle, buffer_m,
                           max_steps=dem.size)
            # Keep the geometry: exposure counting needs to know WHERE the
            # corridor goes, not just how far. Stored as a lon/lat polyline
            # down the channel, decimated to ~1 point per 5 cells - enough to
            # query assets against, far smaller than the raster.
            walk = r.pop("flow_walk", None)
            r.pop("flow_path", None)
            r.pop("corridor", None)
            if walk:
                # In walk order. Sorting by distance from the seed interleaved
                # the bends of a meandering river; see route_long.
                pts = walk[::5] + ([walk[-1]] if (len(walk) - 1) % 5 else [])
                rows = [q[0] for q in pts]
                cols = [q[1] for q in pts]
                xs, ys = rasterio.transform.xy(transform, rows, cols)
                r["polyline_lonlat"] = [[round(float(x), 5), round(float(y), 5)]
                                        for x, y in zip(xs, ys)]
            rec["regimes"][regime] = r

        near = (stage6.get(lid) or {}).get("regimes") or {}
        rec["stage6_max_runout_m"] = max(
            [(v.get("max_runout_m") or 0) for v in near.values()] or [0])
        rec["long_max_runout_m"] = max(
            v["max_runout_m"] for v in rec["regimes"].values())
        rec["gain_factor"] = (
            round(rec["long_max_runout_m"] / rec["stage6_max_runout_m"], 1)
            if rec["stage6_max_runout_m"] else None)
        results.append(rec)

    doc = {
        "n_lakes": len(results),
        "note": ("Long-range routing on a 100 km, 90 m domain. Stage 6 remains "
                 "the near-field result at 10 m; this answers reach, not width."),
        "lakes": sorted(results, key=lambda r: r["lake_id"]),
    }
    SITE.mkdir(parents=True, exist_ok=True)
    write_json(SITE / "long_routing.json", doc)

    print(f"{'lake':<24}{'stage 6':>10}{'long':>10}{'gain':>7}  stop reason")
    for r in doc["lakes"]:
        far = r["long_max_runout_m"] / 1000
        near = r["stage6_max_runout_m"] / 1000
        reason = r["regimes"]["clearwater_flood"]["stop_reason"]
        print(f"{r['lake_id']:<24}{near:>7.2f} km{far:>7.2f} km"
              f"{(str(r['gain_factor']) + 'x') if r['gain_factor'] else '-':>7}  {reason}")
    print(f"\n-> outputs/tools/long_routing.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
