"""Check every registered lake coordinate against where the water actually is.

Run:  python -m src.data.verify_coordinates

Motivation, from a real failure. The registry gave Thyanbo Tsho as 27.83 N,
86.60 E - the only coordinate published for it, from Bisht et al. (2025). The
delineator found a 45,000 m2 water body (against a published 43,902 m2, so
unmistakably the right lake) sitting 2,364 m away, near the very edge of the
5 km window. A point-based pipeline would have measured nothing, or worse,
measured whatever pond happened to sit at the nominal point.

Coordinates in this literature are frequently approximate: papers round to two
decimal places, name a valley rather than a lake, or cite an inventory centroid
that has since moved. Trusting them silently is how an analysis ends up
confidently measuring the wrong thing.

So this runs before any science: delineate on the cleanest annual scenes, take
the dominant water body, and report the offset from the registered position.
Offsets beyond a threshold are flagged for the registry to be corrected and the
window re-fetched around the true location - which also matters for Stage 4,
where the proxies need the full 1,000 m shoreline buffer and the upstream
source area inside the window, not clipped by an off-centre frame.

This is a diagnostic, not part of `reproduce`. Its OUTPUT (corrected
coordinates) is committed; the check itself needs only the pinned data and can
be re-run at any time.
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import rasterio
from pyproj import Transformer
from scipy import ndimage

from src.common.config import REPO_ROOT, load_config
from src.common.io import read_json, write_json
from src.watcher.delineate import water_mask
from src.watcher.qa import usability_score
from src.watcher.qa import assess as qa_assess
from src.watcher.scene import load_scene

# Beyond this, the registered coordinate is treated as wrong rather than merely
# imprecise. Two decimal places of latitude is already +/- ~550 m, so the
# threshold has to sit above rounding noise to avoid crying wolf.
OFFSET_FLAG_M = 800.0

# Scenes to measure on. Annual scenes only: event brackets are chosen for
# timing rather than clarity, and a cloud-obscured scene gives a noisy centroid.
MIN_SCENES_FOR_CONSENSUS = 2

# Two observations belong to the same lake if their centroids fall within this
# distance. Wide enough to absorb year-to-year growth and boundary noise on a
# small lake, tight enough to keep a neighbouring pond in its own cluster.
CLUSTER_RADIUS_M = 400.0


def observed_centroid(scene, cfg) -> tuple[float, float, float, int] | None:
    """(lon, lat, area_m2, n_pixels) of the dominant water body, or None."""
    mask, _ = water_mask(scene, cfg)
    labels, n = ndimage.label(mask)
    if n == 0:
        return None
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    big = int(np.argmax(sizes)) + 1
    npx = int(sizes[big - 1])
    if npx < cfg.require("delineation.min_lake_pixels"):
        return None
    yy, xx = ndimage.center_of_mass(labels == big)
    x, y = rasterio.transform.xy(scene.transform, yy, xx)
    lon, lat = Transformer.from_crs(scene.crs, "EPSG:4326",
                                    always_xy=True).transform(x, y)
    return float(lon), float(lat), float(npx * scene.pixel_area_m2), npx


def metres_between(lon1, lat1, lon2, lat2) -> tuple[float, float, float]:
    """(east_m, north_m, distance_m) from point 1 to point 2."""
    mean_lat = np.radians((lat1 + lat2) / 2.0)
    east = (lon2 - lon1) * 111_320.0 * np.cos(mean_lat)
    north = (lat2 - lat1) * 110_570.0
    return float(east), float(north), float(np.hypot(east, north))


def verify_lake(lake: dict, manifest_lake: dict, cfg) -> dict:
    lid = lake["id"]
    obs = []
    for entry in manifest_lake["scenes"]:
        if entry.get("role") != "annual" or not entry.get("assets"):
            continue
        scene = load_scene(lid, entry)
        if scene is None:
            continue
        qa = qa_assess(scene, cfg)
        c = observed_centroid(scene, cfg)
        if c is None:
            continue
        obs.append({"label": entry["label"], "date": entry["acquired_date"],
                    "lon": c[0], "lat": c[1], "area_m2": c[2], "n_px": c[3],
                    "qa_verdict": qa["verdict"], "score": usability_score(qa)})

    if not obs:
        return {"lake_id": lid, "status": "no_water_found",
                "note": "No water body met the index tests on any annual scene. "
                        "Either the window misses the lake entirely, or every "
                        "scene is unusable.",
                "registered": {"lon": lake["lon"], "lat": lake["lat"]},
                "observations": []}

    # Consensus by SPATIAL MODE, not by QA rank.
    #
    # Ranking on QA and taking the median of the best few looked reasonable and
    # was wrong: with no DEM on the grid, the QA verdict leans on SCL's
    # dark-area class, which is too weak to order scenes reliably. On hongu_1
    # that put the two "ok" scenes - the outliers - ahead of the five scenes
    # that agree with each other to 4 decimal places, and the answer moved
    # ~600 m to the wrong place.
    #
    # Where the lake actually is does not change between years, so the right
    # estimator is the location most scenes agree on. Cluster the observed
    # centroids and take the median of the largest cluster; a scene that lands
    # on a cloud shadow or a neighbouring pond becomes a minority vote instead
    # of a weighted one.
    clusters: list[list[dict]] = []
    for o in obs:
        for c in clusters:
            if metres_between(c[0]["lon"], c[0]["lat"], o["lon"], o["lat"])[2] <= CLUSTER_RADIUS_M:
                c.append(o)
                break
        else:
            clusters.append([o])
    clusters.sort(key=lambda c: (-len(c), -max(x["n_px"] for x in c)))

    def centre(cluster):
        return (float(np.median([o["lon"] for o in cluster])),
                float(np.median([o["lat"] for o in cluster])))

    # The registry is a PRIOR; the imagery is evidence. Taking the largest
    # cluster outright was wrong for the big lakes: South Lhonak and Imja
    # fragment under ice cover, so in those years a neighbouring water body is
    # the biggest component, and "most scenes agree" confidently pointed 2.3 km
    # away from a coordinate that was in fact correct.
    #
    # So: anchor on the cluster nearest the registered position. If one sits
    # close by, the registry is confirmed and we keep it. Only when NOTHING is
    # near the registered point - the Thyanbo case, where the nearest water in
    # any year is 1.5 km away - do we conclude the coordinate is wrong and fall
    # back to the largest cluster as the likely true lake.
    substantial = [c for c in clusters if len(c) >= 2] or clusters
    anchor = min(substantial,
                 key=lambda c: metres_between(lake["lon"], lake["lat"], *centre(c))[2])
    anchor_lon, anchor_lat = centre(anchor)
    anchor_dist = metres_between(lake["lon"], lake["lat"], anchor_lon, anchor_lat)[2]

    if anchor_dist <= OFFSET_FLAG_M:
        best, (lon_obs, lat_obs), status = anchor, (anchor_lon, anchor_lat), "ok"
    else:
        best = clusters[0]
        lon_obs, lat_obs = centre(best)
        status = "offset_flagged"

    spread_m = 0.0
    if len(best) > 1:
        spread_m = float(np.max([metres_between(lon_obs, lat_obs, o["lon"], o["lat"])[2]
                                 for o in best]))

    east, north, dist = metres_between(lake["lon"], lake["lat"], lon_obs, lat_obs)
    return {
        "lake_id": lid,
        "name": lake["name"],
        "status": status,
        "nearest_cluster_distance_m": round(anchor_dist, 1),
        "cluster_sizes": [len(c) for c in clusters],
        "registered": {"lon": lake["lon"], "lat": lake["lat"],
                       "source": lake.get("coordinate_source"),
                       "confidence": lake.get("coordinate_confidence")},
        "observed": {"lon": round(lon_obs, 6), "lat": round(lat_obs, 6),
                     "n_scenes_used": len(best),
                     "n_scenes_total": len(obs),
                     "n_clusters": len(clusters),
                     "consensus": "spatial_mode",
                     "inter_scene_spread_m": round(spread_m, 1)},
        "offset": {"east_m": round(east, 1), "north_m": round(north, 1),
                   "distance_m": round(dist, 1)},
        "median_area_m2": round(float(np.median([o["area_m2"] for o in best])), 1),
        "observations": obs,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lake", action="append")
    args = p.parse_args(argv)

    cfg = load_config()
    lakes_doc = read_json(cfg.path("labels") / "lakes.json")
    manifest = read_json(cfg.path("pinned") / "scenes_manifest.json")
    by_id = {l["lake_id"]: l for l in manifest["lakes"]}

    lakes = lakes_doc["lakes"]
    if args.lake:
        lakes = [l for l in lakes if l["id"] in set(args.lake)]

    results = []
    print(f"{'lake':<22}{'status':<16}{'offset m':>9}{'spread':>8}"
          f"{'area m2':>12}  registered -> observed")
    for lake in lakes:
        ml = by_id.get(lake["id"])
        if ml is None:
            continue
        r = verify_lake(lake, ml, cfg)
        results.append(r)
        if r["status"] == "no_water_found":
            print(f"{lake['id']:<22}{'NO WATER':<16}{'':>9}{'':>8}{'':>12}  "
                  f"{lake['lon']:.4f},{lake['lat']:.4f}")
            continue
        o, off = r["observed"], r["offset"]
        mark = "FLAG" if r["status"] == "offset_flagged" else "ok"
        print(f"{lake['id']:<22}{mark:<16}{off['distance_m']:>9.0f}"
              f"{o['inter_scene_spread_m']:>8.0f}{r['median_area_m2']:>12,.0f}  "
              f"{lake['lon']:.4f},{lake['lat']:.4f} -> {o['lon']:.4f},{o['lat']:.4f}")

    out = REPO_ROOT / "outputs" / "coordinate_verification.json"
    write_json(out, {"offset_flag_threshold_m": OFFSET_FLAG_M, "lakes": results})
    flagged = [r["lake_id"] for r in results if r["status"] == "offset_flagged"]
    nowater = [r["lake_id"] for r in results if r["status"] == "no_water_found"]
    print(f"\nflagged (offset > {OFFSET_FLAG_M:.0f} m): {flagged or 'none'}")
    print(f"no water found: {nowater or 'none'}")
    print(f"report -> {out.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
