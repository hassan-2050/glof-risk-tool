"""Lake delineation: pixels -> one area estimate with its QA record.

The rule, in one line: a pixel is lake water only if it is high in BOTH NDWI
and MNDWI, is not glacier ice by the NIR/SWIR1 ratio, and is not snow. Any
single-index rule counts snow and ice as water in this setting - see the
reflectance table in indices.py.

Choosing WHICH water body is the lake matters as much as finding water. A 5 km
window in the Khumbu contains ponds, meltwater, river channels and sometimes a
neighbouring lake. We take the connected component nearest the registered
centroid, not the largest, because the largest can be an adjacent bigger lake
and would silently swap the subject of the whole analysis. Distance is capped,
so a window with no lake in it (Chamoli, where there is genuinely no lake)
returns zero rather than reaching across the window for something.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from src.watcher import indices as idx
from src.watcher import qa as qa_mod
from src.watcher.scene import SCL_SNOW_ICE, Scene

# A component must lie within this distance of the registered centroid to be
# accepted as the lake. Generous enough to absorb the coordinate uncertainty in
# the registry (some centroids are published to 2 dp, ~1 km), tight enough that
# an unrelated water body across the window is not adopted.
MAX_CENTROID_DISTANCE_M = 1500.0


def water_mask(scene: Scene, cfg) -> tuple[np.ndarray, dict]:
    """Boolean water mask over the window, plus the evidence for each rule."""
    d = cfg.require("delineation")
    ndwi_a = idx.ndwi(scene.green, scene.nir)
    mndwi_a = idx.mndwi(scene.green, scene.swir1)
    ratio = idx.nir_swir1_ratio(scene.nir, scene.swir1)
    ndsi_a = idx.ndsi(scene.green, scene.swir1)

    with np.errstate(invalid="ignore"):
        is_ndwi = ndwi_a > d["ndwi_threshold"]
        is_mndwi = mndwi_a > d["mndwi_threshold"]
        # Huggel et al. 2004a: NIR/SWIR1 above ~2.2 is glacier ice, not water.
        is_glacier = ratio > d["glacier_nir_swir1_ratio"]
        # Snow is bright in NIR; water is not. Both are high in MNDWI/NDSI, so
        # NDWI is the only thing separating them.
        is_snow = (ndsi_a > d["qa"]["snow_index_max"]) & (ndwi_a < 0.20)

    mask = is_ndwi & is_mndwi & ~is_glacier & ~is_snow & scene.valid
    mask &= scene.scl != SCL_SNOW_ICE

    evidence = {
        "px_ndwi_only": int((is_ndwi & scene.valid).sum()),
        "px_mndwi_only": int((is_mndwi & scene.valid).sum()),
        "px_both_indices": int((is_ndwi & is_mndwi & scene.valid).sum()),
        "px_rejected_as_glacier": int((is_ndwi & is_mndwi & is_glacier & scene.valid).sum()),
        "px_rejected_as_snow": int((is_ndwi & is_mndwi & ~is_glacier & is_snow & scene.valid).sum()),
        "px_rejected_by_scl_snow": int((is_ndwi & is_mndwi & ~is_glacier & ~is_snow
                                        & (scene.scl == SCL_SNOW_ICE) & scene.valid).sum()),
        "px_final_water": int(mask.sum()),
    }
    return mask, evidence


# Gap, in pixels, that morphological closing will bridge before components are
# labelled. Measured need: Tsho Rolpa fragmented into 99 components and Imja
# into 239, because thin lines of surface ice, wind-blown debris and floating
# bergs cut a single lake into pieces. Taking the largest raw component then
# reported a quarter of the true area. Closing over ~3 pixels (30 m) rejoins a
# lake split by an ice lead without bridging the ~100 m of moraine that
# separates genuinely distinct lakes.
CLOSING_RADIUS_PX = 3


def select_lake_component(mask: np.ndarray, scene: Scene, cfg,
                          anchor_rc: tuple[float, float] | None = None) -> tuple[np.ndarray, dict]:
    """Pick the connected component that is the lake.

    Fragments are rejoined before labelling, then the chosen component is
    intersected back with the original mask so that closing never invents water
    that was not observed - it only decides which observed pixels belong
    together.

    `anchor_rc` is a (row, col) the lake is known to occupy, established across
    all scenes by the caller. Without it the rule is "largest component near the
    window centre", which is UNSTABLE when a window holds two comparable lakes:
    on Thyanbo it selected the upper lake in 2018/2019/2022 and the lower lake
    in 2021/2024, silently alternating between two different water bodies
    within one area series. That is exactly the Thame geometry - ICIMOD
    describe an upper lake at 4,900 m that breached into a lower
    moraine-dammed lake 120 m below - so the ambiguity is real, not noise, and
    it has to be resolved once per lake rather than independently per scene.
    """
    d = cfg.require("delineation")
    min_px = d["min_lake_pixels"]
    k = 2 * CLOSING_RADIUS_PX + 1
    closed = ndimage.binary_closing(mask, structure=np.ones((k, k)))
    labels, n = ndimage.label(closed)
    if n == 0:
        return np.zeros_like(mask), {"n_components": 0, "selected": None,
                                     "reason": "no water pixels survived the index tests"}

    res_m = float(np.sqrt(scene.pixel_area_m2))
    # Distance is measured from the anchor when one is supplied, otherwise from
    # the window centre (the pass-1 case, before the anchor is known).
    cy, cx = anchor_rc if anchor_rc is not None else tuple(s / 2.0 for s in mask.shape)
    comps = []
    for lab, (sy, sx) in enumerate(ndimage.find_objects(labels), start=1):
        comp = labels[sy, sx] == lab
        size = int(comp.sum())
        if size < min_px:
            continue
        yy, xx = ndimage.center_of_mass(comp)
        gy, gx = yy + sy.start, xx + sx.start
        dist_m = float(np.hypot(gy - cy, gx - cx) * res_m)
        comps.append({"label": lab, "px": size, "distance_m": round(dist_m, 1),
                      "area_m2": size * scene.pixel_area_m2})

    if not comps:
        return np.zeros_like(mask), {
            "n_components": n, "selected": None,
            "reason": f"all {n} components below min_lake_pixels={min_px}"}

    near = [c for c in comps if c["distance_m"] <= MAX_CENTROID_DISTANCE_M]
    if not near:
        closest = min(comps, key=lambda c: c["distance_m"])
        return np.zeros_like(mask), {
            "n_components": n, "selected": None,
            "reason": (f"no water body within {MAX_CENTROID_DISTANCE_M:.0f} m of the "
                       f"registered centroid; nearest is {closest['distance_m']:.0f} m "
                       f"away. Not adopting it - that would silently change which "
                       f"lake is being measured."),
            "components": sorted(comps, key=lambda c: c["distance_m"])[:5]}

    # With an anchor, take the CLOSEST component: the anchor already encodes
    # which of several lakes is the subject, and preferring size there would
    # reintroduce the flip-flop. Without one, fall back to the largest nearby
    # component, since ponds and meltwater fringes are small.
    chosen = (min(near, key=lambda c: c["distance_m"]) if anchor_rc is not None
              else max(near, key=lambda c: c["px"]))
    # Intersect back with the OBSERVED mask: closing decided which pixels group
    # together, it must not add area that was never seen as water.
    selected = (labels == chosen["label"]) & mask
    return selected, {
        "closing_radius_px": CLOSING_RADIUS_PX,
        "px_before_closing": int(mask.sum()),
        "px_selected": int(selected.sum()),
        "n_components": n,
        "n_components_near_centroid": len(near),
        "anchored": anchor_rc is not None,
        "selected": chosen,
        "components": sorted(comps, key=lambda c: -c["px"])[:5],
    }


def delineate(scene: Scene, cfg, dem: np.ndarray | None = None,
              anchor_rc: tuple[float, float] | None = None) -> dict:
    """Full delineation for one scene: area, QA, and the reasoning behind both."""
    mask, evidence = water_mask(scene, cfg)
    lake, selection = select_lake_component(mask, scene, cfg, anchor_rc=anchor_rc)
    area_m2 = float(lake.sum() * scene.pixel_area_m2)

    qa = qa_mod.assess(scene, cfg, dem=dem, lake_mask=lake if lake.any() else None)

    # Boundary-pixel uncertainty. At 10 m a lake of a few hundred pixels has a
    # perimeter that is a real fraction of its area, so a bare number would
    # overstate what Sentinel-2 can resolve here.
    perimeter_px = 0
    if lake.any():
        eroded = ndimage.binary_erosion(lake, structure=np.ones((3, 3)))
        perimeter_px = int((lake & ~eroded).sum())
    area_uncertainty_m2 = 0.5 * perimeter_px * scene.pixel_area_m2

    result = {
        "lake_id": scene.lake_id,
        "label": scene.label,
        "acquired_date": scene.acquired_date,
        "role": scene.role,
        "is_post_event": scene.is_post_event,
        "area_m2": round(area_m2, 1),
        "area_km2": round(area_m2 / 1e6, 6),
        "area_uncertainty_m2": round(area_uncertainty_m2, 1),
        "perimeter_px": perimeter_px,
        "qa": qa,
        "index_evidence": evidence,
        "component_selection": selection,
        "boa_offset_applied": scene.boa_offset,
        "tile_cloud_pct": scene.tile_cloud_pct,
        "method": {
            "rule": "NDWI > t AND MNDWI > t AND NOT glacier(NIR/SWIR1) AND NOT snow",
            "ndwi_threshold": cfg.require("delineation.ndwi_threshold"),
            "mndwi_threshold": cfg.require("delineation.mndwi_threshold"),
            "glacier_ratio_threshold": cfg.require("delineation.glacier_nir_swir1_ratio"),
            "glacier_ratio_source": "Huggel et al. 2004a",
        },
    }
    return result
