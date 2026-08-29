"""Stage 2 pipeline: pinned scenes -> one audited area series per lake.

Two passes, and the second one is the point.

Pass 1 delineates every scene independently. That alone is not enough to judge
a scene, because the tests that matter most - is the lake frozen, is it
partially obscured - are questions about the LAKE, and on a bad scene there is
no lake to ask about. A frozen lake simply looks like a small lake.

Pass 2 fixes that. It builds a reference footprint from the most usable scenes,
then re-runs QA for every scene against that footprint. Now "the lake is 80%
frozen" is answerable even on the scene where almost no open water was found,
because we know where the water should have been. Only then is the best scene
per year chosen, which is what the Stage 2 task means by ranking scenes to
avoid partially-frozen readings.
"""
from __future__ import annotations

import numpy as np
import rasterio
from scipy import ndimage
from rasterio.warp import Resampling as WarpResampling
from rasterio.warp import reproject

from src.common.config import REPO_ROOT
from src.watcher import qa as qa_mod
from src.watcher.delineate import delineate
from src.watcher.scene import Scene, load_scene

# A scene contributes to the reference footprint only if its QA is this good.
FOOTPRINT_VERDICTS = (qa_mod.VERDICT_OK, qa_mod.VERDICT_DEGRADED)
# Footprint = pixels seen as water in at least this fraction of contributing
# scenes. A pure union would absorb every cloud shadow ever mistaken for water;
# a pure intersection would shrink to the minimum extent across years.
FOOTPRINT_MIN_FREQUENCY = 0.30


def load_dem_on_grid(lake_id: str, scene: Scene) -> np.ndarray | None:
    """Read the lake's DEM and warp it onto the scene's grid.

    The DEM is fetched over a wider window than the optical bands and sits in
    geographic coordinates, so it has to be resampled onto the scene's UTM grid
    before it can be compared pixel-for-pixel.
    """
    path = REPO_ROOT / "data" / "pinned" / lake_id / "dem_glo30.tif"
    if not path.exists():
        return None
    dst = np.full(scene.shape, np.nan, dtype="float32")
    try:
        with rasterio.open(path) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=dst,
                src_transform=src.transform, src_crs=src.crs,
                dst_transform=scene.transform, dst_crs=scene.crs,
                resampling=WarpResampling.bilinear,
                src_nodata=src.nodata, dst_nodata=np.nan,
            )
    except Exception:  # noqa: BLE001 - a bad DEM degrades QA, it must not stop the run
        return None
    return dst if np.isfinite(dst).any() else None


def build_reference_footprint(results: list[dict], masks: dict[str, np.ndarray],
                              shape: tuple[int, int]) -> tuple[np.ndarray, dict]:
    """Where the lake is, agreed across the most usable scenes."""
    contributing = [r for r in results
                    if r["qa"]["verdict"] in FOOTPRINT_VERDICTS
                    and masks.get(r["label"]) is not None
                    and masks[r["label"]].any()]
    if not contributing:
        return np.zeros(shape, dtype=bool), {"n_contributing": 0,
                                             "note": "no scene usable enough to define a footprint"}
    stack = np.zeros(shape, dtype="float32")
    for r in contributing:
        stack += masks[r["label"]].astype("float32")
    freq = stack / len(contributing)
    footprint = freq >= FOOTPRINT_MIN_FREQUENCY
    return footprint, {
        "n_contributing": len(contributing),
        "min_frequency": FOOTPRINT_MIN_FREQUENCY,
        "footprint_px": int(footprint.sum()),
        "contributing_labels": sorted(r["label"] for r in contributing),
    }


# Candidate lake positions closer than this are the same lake seen at different
# extents; further apart, they are different water bodies.
ANCHOR_CLUSTER_RADIUS_M = 400.0
# An anchor further than this from the registered coordinate is treated as a
# different lake rather than the intended subject.
MAX_ANCHOR_DISTANCE_M = 800.0
# Clusters within this much of the closest one are treated as equally plausible
# subjects, and vote count decides between them.
TIE_BREAK_BAND_M = 150.0


def find_anchor(scenes: dict[str, Scene], cfg) -> tuple[tuple[float, float] | None, dict]:
    """Decide, once per lake, WHICH water body the series is about.

    Deciding per scene is unstable when a window holds two comparable lakes.
    On Thyanbo that produced an area series alternating between the upper and
    lower lakes of the Thame system - both real lakes, 530 m apart, so no
    per-scene rule could tell which one the series was supposed to track.

    Every water body in every scene votes with its centroid. Votes are
    clustered, and the cluster nearest the registered coordinate wins, with
    support as the tie-break. The window is built around the registered
    coordinate, so the window centre IS the prior. Registry as prior, imagery
    as evidence - the same resolution used for the coordinate check itself.
    """
    from src.watcher.delineate import CLOSING_RADIUS_PX, water_mask

    d = cfg.require("delineation")
    min_px = d["min_lake_pixels"]
    k = 2 * CLOSING_RADIUS_PX + 1

    votes: list[tuple[float, float, int]] = []
    for scene in scenes.values():
        wm, _ = water_mask(scene, cfg)
        if not wm.any():
            continue
        closed = ndimage.binary_closing(wm, structure=np.ones((k, k)))
        labels, n = ndimage.label(closed)
        if n == 0:
            continue
        sizes = ndimage.sum(wm, labels, range(1, n + 1))
        for lab in range(1, n + 1):
            px = int(sizes[lab - 1])
            if px < min_px:
                continue
            yy, xx = ndimage.center_of_mass(labels == lab)
            votes.append((float(yy), float(xx), px))

    if not votes:
        return None, {"anchor": None, "reason": "no candidate water body in any scene"}

    first = next(iter(scenes.values()))
    res_m = float(np.sqrt(first.pixel_area_m2))
    clusters: list[list[tuple[float, float, int]]] = []
    for v in votes:
        for c in clusters:
            if np.hypot(c[0][0] - v[0], c[0][1] - v[1]) * res_m <= ANCHOR_CLUSTER_RADIUS_M:
                c.append(v)
                break
        else:
            clusters.append([v])

    cy, cx = first.shape[0] / 2.0, first.shape[1] / 2.0
    scored = []
    for c in clusters:
        ry = float(np.median([v[0] for v in c]))
        rx = float(np.median([v[1] for v in c]))
        scored.append({
            "row": round(ry, 1), "col": round(rx, 1),
            "votes": len(c),
            "max_area_m2": round(max(v[2] for v in c) * first.pixel_area_m2, 1),
            "distance_from_registered_m": round(float(np.hypot(ry - cy, rx - cx) * res_m), 1),
        })
    # Proximity to the registered coordinate decides; vote count only breaks
    # ties between clusters at comparable distance.
    #
    # Ordering by votes first was wrong and picked the wrong lake: on Thyanbo
    # it preferred a cluster with 27 votes at 662 m over one with 19 votes at
    # 12.5 m, and the 12.5 m cluster is the lake whose 30 Jul 2024 extent
    # matches the published 43,902 m2. Vote count measures how often a water
    # body is the largest thing in the window, which is a fact about its
    # neighbours, not about whether it is the subject. The registered
    # coordinate is the only thing that encodes the subject.
    scored.sort(key=lambda s: s["distance_from_registered_m"])
    tie_band = scored[0]["distance_from_registered_m"] + TIE_BREAK_BAND_M
    contenders = [s for s in scored if s["distance_from_registered_m"] <= tie_band]
    best = max(contenders, key=lambda s: (s["votes"], s["max_area_m2"]))
    return (best["row"], best["col"]), {
        "anchor": best,
        "n_candidate_water_bodies": len(scored),
        "alternatives": scored[1:4],
        "note": ("more than one distinct water body in this window; the series "
                 "tracks the one nearest the registered coordinate"
                 if len(scored) > 1 else "single water body"),
    }


def run_lake(lake: dict, manifest_lake: dict, cfg) -> dict:
    lid = lake["id"]
    scenes: dict[str, Scene] = {}
    masks: dict[str, np.ndarray] = {}
    results: list[dict] = []
    dem = None

    for entry in manifest_lake["scenes"]:
        if not entry.get("assets"):
            continue
        scene = load_scene(lid, entry)
        if scene is None:
            continue
        if dem is None:
            dem = load_dem_on_grid(lid, scene)
        scenes[scene.label] = scene

    if not scenes:
        return {"lake_id": lid, "status": "no_usable_scenes", "scenes": []}

    # --- pass 0: fix WHICH lake this series is about ----------------------
    anchor_rc, anchor_meta = find_anchor(scenes, cfg)

    # --- pass 1: delineate everything against that anchor -----------------
    from src.watcher.delineate import select_lake_component, water_mask
    for label, scene in scenes.items():
        r = delineate(scene, cfg, dem=dem, anchor_rc=anchor_rc)
        wm, _ = water_mask(scene, cfg)
        lake_mask, _ = select_lake_component(wm, scene, cfg, anchor_rc=anchor_rc)
        masks[label] = lake_mask
        results.append(r)

    if not results:
        return {"lake_id": lid, "status": "no_usable_scenes", "scenes": []}

    shape = next(iter(scenes.values())).shape
    footprint, fp_meta = build_reference_footprint(results, masks, shape)

    # --- pass 2: re-assess QA against the footprint ------------------------
    for r in results:
        scene = scenes[r["label"]]
        probe = footprint if footprint.any() else masks.get(r["label"])
        r["qa"] = qa_mod.assess(scene, cfg, dem=dem,
                                lake_mask=probe if probe is not None and probe.any() else None)
        r["qa"]["assessed_against"] = ("reference_footprint" if footprint.any()
                                       else "own_mask")
        r["usability_score"] = round(qa_mod.usability_score(r["qa"]), 4)
        # Fraction of the reference footprint actually seen as open water. This
        # is the number that exposes a frozen lake: area alone cannot, because
        # a frozen lake and a small lake produce the same figure.
        if footprint.any():
            m = masks.get(r["label"])
            r["footprint_open_water_fraction"] = round(
                float((m & footprint).sum()) / float(footprint.sum()), 4) if m is not None else 0.0

    # --- choose one scene per year ----------------------------------------
    by_year: dict[str, list[dict]] = {}
    for r in results:
        if r["role"] != "annual":
            continue
        by_year.setdefault(r["acquired_date"][:4], []).append(r)
    series = []
    for year in sorted(by_year):
        cands = sorted(by_year[year], key=lambda r: (-r["usability_score"],
                                                     -r.get("footprint_open_water_fraction", 0.0)))
        best = cands[0]
        best["selected_for_series"] = True
        best["selection"] = {
            "year": year, "n_candidates": len(cands),
            "rejected": [{"label": c["label"], "date": c["acquired_date"],
                          "score": c["usability_score"],
                          "verdict": c["qa"]["verdict"]} for c in cands[1:]],
        }
        series.append(best)

    # Validation against the published value, reported per lake rather than
    # asserted in prose. Uses the best (largest usable) measurement, since the
    # reference is itself a best-case clear-scene value.
    ref = lake.get("published_reference_area_m2")
    best_area = max((r["area_m2"] for r in results
                     if r["qa"]["verdict"] != "unusable"), default=0.0)
    validation = None
    if ref:
        validation = {
            "published_reference_area_m2": ref,
            "published_reference_source": lake.get("published_reference_source"),
            "best_measured_area_m2": round(best_area, 1),
            "ratio_to_published": round(best_area / ref, 3) if ref else None,
            "within_25pct": abs(best_area / ref - 1.0) <= 0.25 if ref else None,
        }

    return {
        "lake_id": lid,
        "name": lake["name"],
        "class": lake["class"],
        "status": "ok",
        "validation": validation,
        "anchor": anchor_meta,
        "reference_footprint": fp_meta,
        "dem_available": dem is not None,
        "n_scenes": len(results),
        "annual_series": [
            {"year": r["acquired_date"][:4], "date": r["acquired_date"],
             "label": r["label"], "area_m2": r["area_m2"], "area_km2": r["area_km2"],
             "area_uncertainty_m2": r["area_uncertainty_m2"],
             "qa_verdict": r["qa"]["verdict"], "qa_reasons": r["qa"]["reasons"],
             "open_water_fraction": r.get("footprint_open_water_fraction"),
             "n_candidates": r["selection"]["n_candidates"]}
            for r in series
        ],
        "scenes": results,
    }
