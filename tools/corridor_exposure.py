"""What lies along the routed corridor: settlements, bridges, hydropower.

    python -m src.data.fetch_downstream      # DEM, once
    python tools/run_long_routing.py         # corridors
    python tools/corridor_exposure.py        # -> outputs/tools/corridor_exposure.json

NEEDS NETWORK on first run (OpenStreetMap via Overpass). Results are cached to
data/pinned/<lake>/corridor_osm.json so later runs are offline.

WHY THIS IS NOT STAGE 5
-----------------------
Stage 5 counts assets inside a 7 km box around the lake. Across fourteen lakes
that found two buildings and no population, because the corridors stop in the
headwaters above anything worth counting (D11, D18). This counts along the
routed channel instead, over 100 km, which is where the assets actually are.

WHAT IT ANSWERS
    "If this lake releases, what is in the way, and how far down?" - a list of
    named places ordered by distance along the channel.

WHAT IT DOES NOT ANSWER
    Whether any of them floods. There is no depth, no discharge and no
    hydraulics here: an asset is listed if it lies within the corridor buffer,
    which is a screening statement about position, not an inundation call.
"""
from __future__ import annotations

import argparse
import json
import math
import sys

import numpy as np
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.config import REPO_ROOT, load_config          # noqa: E402
from src.common.io import TOOL_OUTPUT_DIR, read_json, write_json  # noqa: E402
from src.data.fetch_exposure import OVERPASS                  # noqa: E402

import requests                                               # noqa: E402

# A corridor query is NOT the Stage 5 query. Stage 5 asks for every building in
# a 7 km box; asking for every building along 100 km of Nepali valley times the
# public Overpass endpoint out with HTTP 504, which is what happened on the
# first run. Buildings are also the least decision-relevant class at this scale
# - a count of houses along 100 km says far less than the names of the
# settlements and the hydropower in the way.
CORRIDOR_QUERY = """[out:json][timeout:300];
(
  node["place"~"^(village|hamlet|town|city)$"]({bbox});
  node["power"~"^(plant|generator|substation)$"]({bbox});
  way["power"~"^(plant|generator|substation)$"]({bbox});
  way["waterway"~"^(dam|weir)$"]({bbox});
  node["amenity"~"^(school|college|hospital|clinic|doctors)$"]({bbox});
  way["amenity"~"^(school|college|hospital|clinic|doctors)$"]({bbox});
  way["bridge"]["highway"]({bbox});
);
out tags center;
"""

# Public mirrors, tried in order. The main endpoint rate-limits and 504s on
# large areas; a single hard-coded host makes the tool fail for reasons that
# have nothing to do with the analysis.
ENDPOINTS = [OVERPASS,
             "https://overpass.kumi.systems/api/interpreter",
             "https://overpass.osm.ch/api/interpreter"]


# Overpass rate-limits by IP across ALL its mirrors, so rotating hosts does not
# buy a fresh quota - only waiting does. 429 (slot exhausted) and 504 (query too
# heavy) both mean "come back later", and the endpoint usually says how much
# later in Retry-After. Backoff is therefore the mechanism that actually works
# here; the mirror list only helps when one host is down rather than throttling.
BACKOFF_S = [30, 90, 240, 600]


def query_corridor(bbox, retries: int = 4) -> dict:
    """bbox is (minlon, minlat, maxlon, maxlat); Overpass wants S,W,N,E."""
    q = CORRIDOR_QUERY.format(bbox=f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}")
    last = None
    for attempt in range(retries):
        wait_hint = 0
        for url in ENDPOINTS:
            host = url.split("/")[2]
            try:
                r = requests.post(
                    url, data=q.encode("utf-8"), timeout=300,
                    headers={"Content-Type": "application/x-www-form-urlencoded",
                             "User-Agent": "glof-risk-tool/0.1 (research "
                                           "prototype; contact via repository)",
                             "Accept": "application/json"})
                if r.status_code == 200:
                    doc = r.json()
                    # An empty element list is treated as a FAILURE, not an
                    # answer. Under load these endpoints return HTTP 200 with
                    # zero elements, and caching that silently turns "the query
                    # failed" into "there is nothing downstream" - which is the
                    # most dangerous wrong answer this tool could give. Two of
                    # four lakes reported no assets along 126 km and 31 km of
                    # Himalayan valley before this check existed.
                    if doc.get("elements"):
                        return doc
                    last = f"{host} returned 0 elements"
                else:
                    last = f"{host} HTTP {r.status_code}"
                    if r.status_code in (429, 504):
                        try:
                            wait_hint = max(wait_hint,
                                            int(r.headers.get("Retry-After", 0)))
                        except ValueError:
                            pass
            except Exception as exc:                     # noqa: BLE001
                last = f"{host} {type(exc).__name__}"
        if attempt < retries - 1:
            nap = max(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)], wait_hint)
            print(f"      all mirrors refused ({last}); waiting {nap}s",
                  flush=True)
            time.sleep(nap)
    raise RuntimeError(f"Overpass failed after {retries} rounds: {last}")

OUT = REPO_ROOT / "outputs"
SITE = OUT / TOOL_OUTPUT_DIR

# Half-width of the band searched either side of the channel. The corridor is a
# 90 m flow line, and a Himalayan valley floor is commonly a few hundred metres
# across, so 500 m is "in this valley" rather than a claim about inundation.
CORRIDOR_BUFFER_M = 500.0

ASSET_CLASSES = {
    "settlement": lambda tg: tg.get("place") in
        {"village", "hamlet", "town", "city"},
    "hydropower": lambda tg: tg.get("power") in {"plant", "generator"}
        or tg.get("waterway") in {"dam", "weir"},
    "substation": lambda tg: tg.get("power") == "substation",
    "bridge": lambda tg: "bridge" in tg,
    "school": lambda tg: tg.get("amenity") in
        {"school", "college", "kindergarten"},
    "health": lambda tg: tg.get("amenity") in
        {"hospital", "clinic", "doctors", "pharmacy"},
    "road": lambda tg: tg.get("highway") in
        {"trunk", "primary", "secondary", "tertiary"},
    "building": lambda tg: "building" in tg,
}
# Checked in order; a node tagged both place and building is a settlement.
CLASS_ORDER = ["settlement", "hydropower", "substation", "bridge", "school",
               "health", "road", "building"]


def _bbox_of(points, pad_deg: float = 0.02):
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lons) - pad_deg, min(lats) - pad_deg,
            max(lons) + pad_deg, max(lats) + pad_deg)


def _metres_between(a, b, lat0: float):
    dx = (a[0] - b[0]) * 111320.0 * math.cos(math.radians(lat0))
    dy = (a[1] - b[1]) * 110574.0
    return math.hypot(dx, dy)


def _along_channel(point, polyline, lat0: float):
    """Distance to the channel, and how far down it, in metres.

    Returns (perpendicular distance, along-channel distance). The polyline is
    already ordered from the lake outwards, so the index of the nearest vertex
    is a usable measure of "how far downstream".
    """
    best_d, best_i = float("inf"), 0
    for i, v in enumerate(polyline):
        d = _metres_between(point, v, lat0)
        if d < best_d:
            best_d, best_i = d, i
    along = 0.0
    for i in range(1, best_i + 1):
        along += _metres_between(polyline[i - 1], polyline[i], lat0)
    return best_d, along


def classify(tags: dict) -> str | None:
    for name in CLASS_ORDER:
        if ASSET_CLASSES[name](tags):
            return name
    return None


def _nearest_populated(arr, tr, polyline) -> tuple:
    """Distance to the closest populated cell, and the people within 2 km.

    Only called when the buffer itself sums to zero. A zero inside a 500 m band
    is a true statement about the band and a false one about the valley, and
    without this the two are indistinguishable in the output.
    """
    rows, cols = np.where(np.isfinite(arr) & (arr > 0))
    if rows.size == 0:
        return None, 0.0
    lat0 = sum(p[1] for p in polyline) / len(polyline)
    mx = 111320.0 * math.cos(math.radians(lat0))
    # Every vertex, not a decimated subset: decimating overstated Gokyo's
    # nearest cell as 885 m when it is 696 m, and a distance quoted in the
    # output should not carry a 27% error it does not need to. Cost is bounded
    # by the chunk loop below, not by the vertex count.
    verts = np.asarray(polyline, dtype="float64")
    xs = tr.c + (cols + 0.5) * tr.a
    ys = tr.f + (rows + 0.5) * tr.e
    best = np.empty(rows.size, dtype="float64")
    for i in range(0, rows.size, 4096):                 # bounded memory
        sl = slice(i, i + 4096)
        dx = (xs[sl, None] - verts[None, :, 0]) * mx
        dy = (ys[sl, None] - verts[None, :, 1]) * 110574.0
        best[sl] = np.sqrt(dx * dx + dy * dy).min(axis=1)
    vals = arr[rows, cols]
    return float(best.min()), round(float(vals[best <= 2000.0].sum()), 1)


def population_along(polyline, worldpop_path: Path, buffer_m: float) -> dict:
    """People within `buffer_m` of the channel, from the WorldPop 100 m grid.

    Summed on WorldPop's OWN grid, so no cell-area rescaling is needed. The
    Stage 5 version warps to a 10 m scene grid and must divide by 100; doing
    that here would be wrong by two orders of magnitude in the other direction.

    WorldPop "constrained" assigns people only where buildings are detected, so
    zero over an uninhabited gorge is a measured absence, not a gap. The raster
    is Nepal-only, so a corridor crossing into Tibet or India is partially
    uncovered - that fraction is reported rather than silently counted as zero.
    """
    import rasterio
    from rasterio.windows import from_bounds

    lons = [q[0] for q in polyline]
    lats = [q[1] for q in polyline]
    pad = buffer_m / 100000.0
    try:
        with rasterio.open(worldpop_path) as src:
            win = from_bounds(min(lons) - pad, min(lats) - pad,
                              max(lons) + pad, max(lats) + pad,
                              transform=src.transform)
            arr = src.read(1, window=win, boundless=True,
                           fill_value=float("nan")).astype("float64")
            tr = src.window_transform(win)
            nodata = src.nodata
            bounds = src.bounds
    except Exception as exc:                              # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    if nodata is not None:
        arr[arr == nodata] = np.nan
    h, w = arr.shape
    if h == 0 or w == 0:
        return {"available": False, "reason": "corridor outside the raster"}

    # Which window cells lie inside the source raster's own extent. A boundless
    # read pads with NaN beyond that extent, and those pads are the only cells
    # that count as "not covered".
    xs = tr.c + (np.arange(w) + 0.5) * tr.a
    ys = tr.f + (np.arange(h) + 0.5) * tr.e
    in_bounds = (((xs >= bounds.left) & (xs <= bounds.right))[None, :]
                 & ((ys >= bounds.bottom) & (ys <= bounds.top))[:, None])

    # Paint a disc of buffer radius around each vertex. Cheaper and clearer
    # than a full distance transform, and the polyline is already decimated.
    res_m = abs(tr.a) * 111320.0 * math.cos(math.radians(sum(lats) / len(lats)))
    rad = max(1, int(round(buffer_m / max(res_m, 1e-6))))
    mask = np.zeros((h, w), dtype=bool)
    rr, cc = np.ogrid[:h, :w]
    for lon, lat in polyline:
        col, row = ~tr * (lon, lat)
        r0, c0 = int(row), int(col)
        if -rad <= r0 < h + rad and -rad <= c0 < w + rad:
            mask |= ((rr - r0) ** 2 + (cc - c0) ** 2) <= rad ** 2

    if not mask.any():
        return {"available": False, "reason": "no corridor cells on the grid"}

    # Coverage means "inside the raster", NOT "has a population value".
    #
    # WorldPop constrained is nodata wherever no building was detected, which
    # over a Himalayan gorge is most cells - and a measured zero, not a gap.
    # Scoring coverage as finite/total conflated the two and reported "0% of
    # the corridor covered" beside a population of 5,222, which is a
    # self-contradiction. Only cells outside the raster's own bounds are
    # genuinely uncovered.
    outside_raster = mask & ~in_bounds
    covered_cells = int(mask.sum() - outside_raster.sum())
    if covered_cells == 0:
        # Chamoli and South Lhonak sit in India; the Nepal raster has nothing
        # to say about them. Returning population 0 here would be read as "no
        # one lives downstream" - the same conflation this function exists to
        # avoid - so say there is no measurement instead.
        return {"available": False,
                "reason": "corridor lies entirely outside the Nepal raster"}
    vals = np.where(np.isfinite(arr), arr, 0.0)[mask & in_bounds]
    total = float(vals.sum())

    # People as a function of reach. The scenario dial asks "if the flow runs
    # R km, how many people are within the band up to there?" - answerable
    # from the same grid by binning each populated cell at its along-channel
    # distance. Populated cells are sparse (tens to hundreds), so the nearest-
    # vertex search is cheap.
    vert_cum = [0.0]
    lat0 = polyline[0][1]
    for i in range(1, len(polyline)):
        vert_cum.append(vert_cum[-1]
                        + _metres_between(polyline[i - 1], polyline[i], lat0))
    pts = np.asarray(polyline, dtype="float64")
    mx = 111320.0 * math.cos(math.radians(lat0))
    bins: dict[int, float] = {}
    prow, pcol = np.where((np.nan_to_num(arr) > 0) & mask & in_bounds)
    for r_, c_ in zip(prow, pcol):
        x, y = tr * (c_ + 0.5, r_ + 0.5)
        d2 = ((pts[:, 0] - x) * mx) ** 2 + ((pts[:, 1] - y) * 110574.0) ** 2
        km = int(vert_cum[int(np.argmin(d2))] / 1000.0)
        bins[km] = bins.get(km, 0.0) + float(arr[r_, c_])
    cum, acc = [], 0.0
    for km in sorted(bins):
        acc += bins[km]
        cum.append([km, round(acc, 1)])

    out = {
        "cum_km": cum,
        "available": True,
        "population": round(total, 1),
        "cells_in_buffer": int(mask.sum()),
        "cells_inside_raster": covered_cells,
        "coverage_fraction": round(covered_cells / float(mask.sum()), 3),
        "grid": "WorldPop 2020 constrained, 100 m, Nepal only",
        "note": ("Summed on the native 100 m grid. Cells outside Nepal are "
                 "uncovered, not zero - see coverage_fraction. WorldPop "
                 "constrained assigns people only where buildings are "
                 "detected, so nodata INSIDE the raster is a measured zero and "
                 "is summed as such; only cells outside the raster extent "
                 "reduce coverage_fraction."),
    }
    if total < 1.0:
        # Gokyo routes past 21 OSM settlements and still sums to zero, because
        # the nearest WorldPop cell sits 696 m from the channel and the buffer
        # is 500 m. The zero is true of the band and false of the valley, so it
        # does not travel on its own.
        near_m, within_2km = _nearest_populated(arr, tr, polyline)
        out["nearest_populated_cell_m"] = (round(near_m) if near_m is not None
                                           else None)
        out["population_within_2km"] = within_2km
        out["zero_note"] = (
            "Zero people within {:.0f} m of the channel. This is a statement "
            "about the buffer, NOT about the valley: WorldPop puts people on "
            "detected building footprints, which sit above the channel on the "
            "valley shoulder more often than on it.".format(buffer_m)
            + ("" if near_m is None else
               " Nearest populated cell {:,.0f} m away; {:,.0f} people within "
               "2 km.".format(near_m, within_2km)))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--refresh", action="store_true",
                   help="re-query Overpass even if a cached extract exists")
    p.add_argument("--regime", default="clearwater_flood",
                   choices=["clearwater_flood", "debris_flow"],
                   help="which corridor to count along (default: the longer)")
    args = p.parse_args(argv)

    cfg = load_config()
    pinned = cfg.path("pinned")
    long_doc = read_json(SITE / "long_routing.json")

    results = []
    for rec in long_doc["lakes"]:
        lid = rec["lake_id"]
        line = (rec["regimes"].get(args.regime) or {}).get("polyline_lonlat")
        if not line or len(line) < 2:
            # No corridor means nothing was queried, so this lake has no
            # asset count either - and must not render as a count of zero.
            results.append({"lake_id": lid, "skipped": "no corridor geometry",
                            "osm_available": False,
                            "osm_error": "no corridor geometry to query along"})
            print(f"  {lid}: no corridor geometry"); continue

        lat0 = float(line[0][1])
        cache = pinned / lid / "corridor_osm.json"
        osm_error = None
        if cache.exists() and not args.refresh:
            osm = read_json(cache)
        else:
            print(f"  {lid}: querying Overpass over {len(line)} vertices ...",
                  flush=True)
            try:
                osm = query_corridor(_bbox_of(line))
            except RuntimeError as exc:
                # A throttled lake must not abort the other thirteen, and must
                # not be allowed to LOOK like a lake with nothing downstream.
                # The record carries osm_available false so every consumer has
                # to say "not queried" instead of printing an empty asset list.
                osm, osm_error = {"elements": []}, str(exc)
                print(f"  {lid}: {exc}")
                print("      -> recorded as NOT QUERIED, not as empty")
            else:
                write_json(cache, osm)
                time.sleep(5)      # be a good citizen on a free endpoint

        counts: dict[str, int] = {}
        named: list[dict] = []
        asset_km: dict[str, list] = {}
        for el in osm.get("elements", []):
            tags = el.get("tags") or {}
            cls = classify(tags)
            if cls is None:
                continue
            lon = el.get("lon") or (el.get("center") or {}).get("lon")
            lat = el.get("lat") or (el.get("center") or {}).get("lat")
            if lon is None or lat is None:
                continue
            perp, along = _along_channel((lon, lat), line, lat0)
            if perp > CORRIDOR_BUFFER_M:
                continue
            counts[cls] = counts.get(cls, 0) + 1
            asset_km.setdefault(cls, []).append(round(along / 1000.0, 1))
            name = tags.get("name")
            if name and cls in {"settlement", "hydropower", "substation",
                                "school", "health"}:
                named.append({"name": name, "class": cls,
                              "along_channel_km": round(along / 1000.0, 1),
                              "offset_m": round(perp),
                              # For drawing on the map; 5 dp is ~1 m.
                              "lon": round(lon, 5), "lat": round(lat, 5)})

        named.sort(key=lambda a: a["along_channel_km"])

        wp = pinned / "exposure" / "worldpop_npl_2020_constrained.tif"
        pop = (population_along(line, wp, CORRIDOR_BUFFER_M) if wp.exists()
               else {"available": False, "reason": "worldpop raster not fetched"})
        results.append({
            "lake_id": lid, "name": rec["name"], "regime": args.regime,
            "osm_available": osm_error is None,
            "osm_error": osm_error,
            "corridor_length_km": round(rec["regimes"][args.regime]
                                        ["max_runout_m"] / 1000.0, 1),
            "buffer_m": CORRIDOR_BUFFER_M,
            "counts": dict(sorted(counts.items())),
            "asset_km": {k: sorted(v) for k, v in sorted(asset_km.items())},
            "population_in_corridor": pop,
            "named_assets": named,
            "n_named": len(named),
        })
        tot = sum(counts.values())
        if not pop.get("available"):
            ptxt = f", population not measured ({pop.get('reason', 'unknown')})"
        elif pop.get("zero_note"):
            near = pop.get("nearest_populated_cell_m")
            ptxt = (", no people within the buffer"
                    + ("" if near is None else
                       f" (nearest populated cell {near:,.0f} m out, "
                       f"~{pop['population_within_2km']:,.0f} within 2 km)"))
        else:
            ptxt = (f", ~{pop['population']:,.0f} people "
                    f"({pop['coverage_fraction']:.0%} of the corridor inside "
                    "the raster)")
        atxt = (f"{tot} assets ({len(named)} named)" if osm_error is None
                else "assets NOT QUERIED (Overpass unavailable)")
        print(f"  {lid}: {atxt} within {CORRIDOR_BUFFER_M:.0f} m of "
              f"{results[-1]['corridor_length_km']} km of channel{ptxt}")

    # Lakes that HAVE a corridor but no OSM answer. A lake with no corridor at
    # all is a routing outcome, not an Overpass failure, and is reported as
    # such rather than padding this list.
    missing = [r["lake_id"] for r in results
               if r.get("osm_available") is False and "skipped" not in r]
    doc = {
        "regime": args.regime,
        "buffer_m": CORRIDOR_BUFFER_M,
        "source": "OpenStreetMap contributors, ODbL",
        "lakes_without_osm": missing,
        "lakes_without_osm_note": ("Overpass did not answer for these lakes. "
                                   "Their asset counts are ABSENT, not zero; "
                                   "re-run the tool to fill them in."),
        "caveat": ("Position, not inundation. An asset is listed because it "
                   "lies within the buffer of a routed channel; nothing here "
                   "models depth, discharge or whether water reaches it."),
        "lakes": results,
    }
    SITE.mkdir(parents=True, exist_ok=True)
    write_json(SITE / "corridor_exposure.json", doc)
    print("\n-> outputs/tools/corridor_exposure.json")
    if missing:
        print(f"NOT QUERIED ({len(missing)}): " + ", ".join(missing)
              + " - asset counts are absent, not zero. Re-run to fill in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
