"""Stage 4: dam-failure and mass-movement proxies.

This is the stage that is supposed to catch Thame. Area-growth screening misses
Thyanbo Tsho because the lake was small and stable; what made it dangerous was
the terrain above it and the geometry of its dam. Every proxy here is a
published criterion computed from free data, and each is emitted as its own
field with its own source and confidence tier so the reporter can cite WHICH
proxy fired rather than quoting an opaque score.

Confidence tiers, carried into every output record:
  published  an explicit numeric threshold in a peer-reviewed paper
  moderate   published but weakly sourced, non-English, or small-n
  derived    our own construction; must be justified, never presented as
             established

Nothing here is combined into a single number. A hazard score would be easier
to rank and impossible to argue with, and the whole point of the project is
that a reviewer should be able to see the reasoning and disagree with a
specific step.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from src.watcher import indices as idx
from src.watcher import terrain as tr


def _record(name: str, value, fired: bool | None, cfg, cite_key: str,
            detail: dict | None = None, tier: str | None = None) -> dict:
    c = cfg.cite(cite_key) if cite_key else {"source": "derived", "confidence_tier": "derived"}
    return {
        "proxy": name,
        "value": value,
        "fired": fired,
        "source": c["source"],
        "confidence_tier": tier or c["confidence_tier"],
        "detail": detail or {},
    }


# --------------------------------------------------------------------------
# 1. Volume from area
# --------------------------------------------------------------------------

def volume_band(area_m2: float, cfg) -> dict:
    """Lake volume as an ORDER-OF-MAGNITUDE BAND, never a point estimate.

    Two published area-volume relations disagree by design, and Cook & Quincey
    (2015) show individual estimates carry 50 to >400% error with area-depth
    correlation of only r2=0.38. Reporting a single number here would be the
    most misleading thing this pipeline could do, so the caveat travels inside
    the output record rather than living in a footnote.
    """
    h = cfg.require("proxies.volume_area.huggel_2002")
    cq = cfg.require("proxies.volume_area.cook_quincey_2015")
    err_lo, err_hi = cfg.require("proxies.volume_area.error_range_pct")

    if area_m2 <= 0:
        return _record("volume_band", None, None, cfg, "proxies.volume_area.huggel_2002",
                       {"note": "no lake area; volume undefined"})

    v_h = h["coeff"] * area_m2 ** h["exp"]
    v_cq = cq["coeff"] * area_m2 ** cq["exp"]
    central = float(np.sqrt(v_h * v_cq))  # geometric mean of the two relations
    lo = min(v_h, v_cq) * (1.0 - err_lo / 100.0)
    hi = max(v_h, v_cq) * (1.0 + err_hi / 100.0)

    return _record(
        "volume_band", {"low_m3": round(lo, 0), "central_m3": round(central, 0),
                        "high_m3": round(hi, 0)},
        None, cfg, "proxies.volume_area.huggel_2002",
        {
            "huggel_2002_m3": round(v_h, 0),
            "cook_quincey_2015_m3": round(v_cq, 0),
            "spread_between_relations_pct": round(100.0 * abs(v_h - v_cq) / min(v_h, v_cq), 1),
            "stated_error_range_pct": [err_lo, err_hi],
            "caveat": ("Area-depth correlation is weak (r2=0.38) and the "
                       "area-volume correlation (r2=0.91) is partly "
                       "autocorrelated. Individual estimates carry 50 to >400% "
                       "error. Use the band, not the central value."),
            "r2_area_depth": cfg.require("proxies.volume_area.r2_area_depth"),
            "r2_area_volume": cfg.require("proxies.volume_area.r2_area_volume"),
        })


# --------------------------------------------------------------------------
# 2. Steep Lakefront Area
# --------------------------------------------------------------------------

def steep_lakefront_area(dem, lake, res_m, level, cfg) -> dict:
    """Fujita et al. (2013): terrain within 1 km at depression angle >10 deg.

    Lakes with no steep lakefront produced no GLOFs in their sample, which
    makes this a genuine screening criterion rather than a correlate.
    """
    key = "proxies.steep_lakefront_area"
    if dem is None or not lake.any() or level is None:
        return _record("steep_lakefront_area", None, None, cfg, key,
                       {"note": "no DEM or no lake"})
    buf_m = cfg.require(f"{key}.buffer_m")
    ang_t = cfg.require(f"{key}.depression_angle_deg")

    dist = tr.distance_to_m(lake, res_m)
    buffer_zone = (dist > 0) & (dist <= buf_m) & np.isfinite(dem)
    if not buffer_zone.any():
        return _record("steep_lakefront_area", None, None, cfg, key,
                       {"note": "buffer empty"})
    ang = tr.depression_angle(dem, lake, res_m, level)
    steep = buffer_zone & (ang > ang_t)
    frac = float(steep.sum()) / float(buffer_zone.sum())
    px_area = res_m * res_m
    return _record(
        "steep_lakefront_area", round(frac, 4), bool(frac > 0.0), cfg, key,
        {"buffer_m": buf_m, "depression_angle_threshold_deg": ang_t,
         "steep_area_m2": round(steep.sum() * px_area, 1),
         "buffer_area_m2": round(buffer_zone.sum() * px_area, 1),
         "max_depression_angle_deg": round(float(np.nanmax(ang[buffer_zone])), 1),
         "interpretation": ("Fujita et al. found no GLOFs from lakes with zero "
                            "steep lakefront; a non-zero fraction is necessary "
                            "but far from sufficient.")})


# --------------------------------------------------------------------------
# 3. Mass-movement source areas
# --------------------------------------------------------------------------

def source_area_slopes(dem, lake, glacier, res_m, level, cfg) -> list[dict]:
    """Detachment zones above the lake, classified by process.

    Ice avalanche and rockfall are separated by whether the surface is
    glacierised, because the same slope means different things on ice and on
    rock. Snow-avalanche starting zones are tagged separately and NOT merged
    with ice: it is a different process with a different runout, and conflating
    them would inflate the apparent ice-avalanche hazard.
    """
    key = "proxies.source_area_slope"
    out = []
    if dem is None or not lake.any() or level is None:
        return [_record("source_area_slope", None, None, cfg, key,
                        {"note": "no DEM or no lake"})]

    ice_lo, ice_hi = cfg.require(f"{key}.ice_avalanche_deg")
    rock_min = cfg.require(f"{key}.rock_landslide_min_deg")
    snow_lo, snow_hi = cfg.require(f"{key}.snow_avalanche_deg")
    ava_reach = cfg.require(f"{key}.avalanche_reach_angle_deg")
    rock_reach = cfg.require(f"{key}.rockfall_reach_angle_deg")

    slope = tr.slope_deg(dem, res_m)
    reach = tr.reach_angle_to(dem, lake, res_m, level)
    above = np.isfinite(dem) & (dem > level) & ~lake
    px_area = res_m * res_m
    gl = glacier if glacier is not None else np.zeros_like(lake)

    for name, lo, hi, on_ice, reach_t in (
            ("ice_avalanche_source", ice_lo, ice_hi, True, ava_reach),
            ("rock_landslide_source", rock_min, 90.0, False, rock_reach),
            ("snow_avalanche_source", snow_lo, snow_hi, True, ava_reach)):
        surface = gl if on_ice else ~gl
        zone = above & surface & (slope >= lo) & (slope <= hi)
        # Only sources that can actually reach the lake count.
        reaching = zone & (reach > reach_t)
        area, n = tr.largest_region_area_m2(reaching, res_m)
        total = float(reaching.sum() * px_area)
        out.append(_record(
            name, round(total, 1), bool(total > 0), cfg, key,
            {"slope_window_deg": [lo, hi],
             "on_glacierised_terrain": on_ice,
             "reach_angle_threshold_deg": reach_t,
             "total_source_area_m2": round(total, 1),
             "largest_contiguous_source_m2": round(area, 1),
             "n_source_patches": n,
             "candidate_area_before_reach_filter_m2": round(float(zone.sum() * px_area), 1),
             "note": ("Snow-avalanche zones are reported separately from ice; "
                      "different process, different runout."
                      if name.startswith("snow") else None)}))
    return out


# --------------------------------------------------------------------------
# 4. Mother-glacier proximity
# --------------------------------------------------------------------------

def mother_glacier(lake, glacier, res_m, cfg) -> dict:
    """Rounce et al. (2016): contact or within 600 m auto-flags dynamic failure.

    When true, freeboard is treated as ZERO regardless of what the DEM says,
    because a calving front delivers ice directly into the water and the dam
    crest stops being the controlling geometry.
    """
    key = "proxies.mother_glacier"
    d_t = cfg.require(f"{key}.contact_distance_m")
    if glacier is None or not glacier.any() or not lake.any():
        return _record("mother_glacier_proximity", None, None, cfg, key,
                       {"note": "no glacier mask or no lake"})
    dist = tr.distance_to_m(glacier, res_m)
    d = float(dist[lake].min())
    fired = d <= d_t
    return _record(
        "mother_glacier_proximity", round(d, 1), bool(fired), cfg, key,
        {"threshold_m": d_t, "in_contact": bool(d <= res_m),
         "consequence": ("freeboard forced to zero per Rounce et al. 2016"
                         if fired else "freeboard estimated from the DEM")})


# --------------------------------------------------------------------------
# 5. Freeboard
# --------------------------------------------------------------------------

def freeboard(dem, lake, res_m, level, cfg, glacier_contact: bool) -> dict:
    """Height of the dam crest above the lake surface; flagged below 25 m.

    Low confidence by construction. A moraine crest is often narrower than a
    30 m pixel, and a DSM smooths exactly the feature being measured, so this
    is reported as an indicative minimum rather than a survey value.
    """
    key = "proxies.freeboard"
    min_safe = cfg.require(f"{key}.min_safe_m")
    if glacier_contact:
        return _record("freeboard", 0.0, True, cfg, key,
                       {"threshold_m": min_safe,
                        "basis": "forced to zero: lake in contact with or within "
                                 "600 m of its parent glacier (Rounce et al. 2016)"},
                       tier="published")
    if dem is None or not lake.any() or level is None:
        return _record("freeboard", None, None, cfg, key, {"note": "no DEM or no lake"})

    ring = tr.shoreline(lake)
    if not ring.any():
        return _record("freeboard", None, None, cfg, key, {"note": "no shoreline"})
    rise = dem[ring] - level
    rise = rise[np.isfinite(rise)]
    if not rise.size:
        return _record("freeboard", None, None, cfg, key, {"note": "no valid shoreline elevations"})
    # The lowest point on the rim controls overtopping.
    fb_raw = float(np.percentile(rise, 10))
    # A negative freeboard is physically impossible - the rim cannot sit below
    # the water it impounds. It means the DSM and our water mask disagree at
    # the shoreline, which happens because GLO-30 predates the imagery, radar
    # behaves oddly over water, and a 30 m pixel straddles the rim. Clamped to
    # zero and marked unreliable rather than reported as a number.
    dem_unreliable = fb_raw < 0.0
    fb = max(fb_raw, 0.0)
    return _record(
        "freeboard", round(fb, 1), bool(fb < min_safe), cfg, key,
        {"threshold_m": min_safe,
         "raw_estimate_m": round(fb_raw, 1),
         "dem_shoreline_unreliable": dem_unreliable,
         "shoreline_rise_p10_m": round(fb, 1),
         "shoreline_rise_median_m": round(float(np.median(rise)), 1),
         "confidence_note": ("30 m DSM; a moraine crest is often narrower than one "
                             "pixel, so this is an indicative minimum, not a "
                             "surveyed freeboard")},
        tier="moderate")


# --------------------------------------------------------------------------
# 6. Distal moraine slope
# --------------------------------------------------------------------------

def distal_moraine_slope(dem, lake, res_m, level, cfg) -> dict:
    """Outer face of the dam; >20 deg indicates instability (Lv et al. 1999).

    Moderate confidence: the source is Chinese-language and we have not
    independently verified the derivation, which is recorded in the output
    rather than smoothed over.
    """
    key = "proxies.distal_moraine_slope"
    max_safe = cfg.require(f"{key}.max_safe_deg")
    if dem is None or not lake.any() or level is None:
        return _record("distal_moraine_slope", None, None, cfg, key,
                       {"note": "no DEM or no lake"})
    dist = tr.distance_to_m(lake, res_m)
    # The distal flank: just outside the lake and BELOW its surface, i.e. the
    # downstream face rather than the enclosing valley walls.
    band = (dist > res_m) & (dist <= 300.0) & np.isfinite(dem) & (dem < level)
    if not band.any():
        return _record("distal_moraine_slope", None, None, cfg, key,
                       {"note": "no downstream face found within 300 m; lake may be "
                                "bedrock-confined or the outlet lies outside the window"})
    slope = tr.slope_deg(dem, res_m)
    val = float(np.percentile(slope[band], 90))
    return _record(
        "distal_moraine_slope", round(val, 1), bool(val > max_safe), cfg, key,
        {"threshold_deg": max_safe, "p90_slope_deg": round(val, 1),
         "median_slope_deg": round(float(np.median(slope[band])), 1),
         "band_area_m2": round(float(band.sum() * res_m * res_m), 1),
         "confidence_note": "Lv et al. 1999 is Chinese-language and not independently verified"})


# --------------------------------------------------------------------------
# 7. Impulse wave from mass flow into the lake
# --------------------------------------------------------------------------

def impulse_wave(dem, lake, glacier, res_m, level, cfg) -> dict:
    """Allen et al. (2019) / Rounce et al. (2017): reach angle >14 deg AND
    source volume >0.1e6 m3 can generate a displacement wave.

    The volume term is the weak link. A detachment volume cannot be measured
    from a single DSM, so it is estimated as source area times an assumed
    failure depth and tagged `derived`. The reach-angle half of the criterion
    is published and computed properly; the output separates the two so a
    reviewer can accept one and reject the other.
    """
    key = "proxies.impulse_wave"
    ang_t = cfg.require(f"{key}.reach_angle_min_deg")
    vol_t = cfg.require(f"{key}.source_volume_min_m3")
    depth = cfg.require(f"{key}.assumed_failure_depth_m")
    slope_min = cfg.require("proxies.source_area_slope.rock_landslide_min_deg")

    if dem is None or not lake.any() or level is None:
        return _record("impulse_wave", None, None, cfg, key, {"note": "no DEM or no lake"})

    slope = tr.slope_deg(dem, res_m)
    reach = tr.reach_angle_to(dem, lake, res_m, level)
    steep_above = np.isfinite(dem) & (dem > level) & ~lake & (slope >= slope_min)
    can_reach = steep_above & (reach > ang_t)
    if not can_reach.any():
        return _record("impulse_wave", 0.0, False, cfg, key,
                       {"reach_angle_threshold_deg": ang_t,
                        "note": "no steep source above the lake exceeds the reach angle"})

    area, n = tr.largest_region_area_m2(can_reach, res_m)
    # Taking the largest contiguous steep patch as one detachment gave 207e6 m3
    # at Thyanbo - eight times the Chamoli avalanche, and physically absurd. A
    # whole valley wall is not a failure plane. Real detachments occupy a small
    # fraction of the terrain that could in principle fail, so the estimate now
    # uses a release fraction and is reported as a band. Both numbers are
    # derived, not published, and the record says so.
    release_frac = cfg.require("proxies.impulse_wave.release_area_fraction")
    est_vol = area * release_frac * depth
    est_vol_max = area * depth
    fired = est_vol > vol_t
    return _record(
        "impulse_wave", round(est_vol, 0), bool(fired), cfg, key,
        {"reach_angle_threshold_deg": ang_t,
         "volume_threshold_m3": vol_t,
         "largest_source_area_m2": round(area, 1),
         "n_source_patches": n,
         "assumed_failure_depth_m": depth,
         "release_area_fraction": release_frac,
         "volume_upper_bound_if_whole_zone_failed_m3": round(est_vol_max, 0),
         "max_reach_angle_deg": round(float(np.nanmax(reach[can_reach])), 1),
         "volume_confidence": "derived",
         "volume_caveat": ("estimated as source area x an assumed uniform failure "
                           "depth; a single DSM cannot constrain detachment "
                           "thickness. The reach-angle test is published; the "
                           "volume test is not.")})


# --------------------------------------------------------------------------
# 8. Calving onset
# --------------------------------------------------------------------------

def calving_onset(lake, glacier, res_m, cfg, glacier_contact: bool) -> dict:
    """Sakai et al. (2009): calving-driven expansion begins past ~80 m fetch."""
    key = "proxies.calving_onset"
    fetch_t = cfg.require(f"{key}.fetch_min_m")
    if not lake.any():
        return _record("calving_onset", None, None, cfg, key, {"note": "no lake"})
    f = tr.fetch_m(lake, res_m)
    fired = bool(f > fetch_t and glacier_contact)
    return _record(
        "calving_onset", round(f, 1), fired, cfg, key,
        {"threshold_m": fetch_t, "fetch_m": round(f, 1),
         "requires_glacier_contact": True,
         "glacier_contact": glacier_contact,
         "note": ("fetch exceeds the calving-onset threshold but the lake is not "
                  "in glacier contact, so calving is not expected"
                  if f > fetch_t and not glacier_contact else None)})


# --------------------------------------------------------------------------
# glacier mask
# --------------------------------------------------------------------------

def glacier_mask(scene, cfg) -> np.ndarray:
    """Glacier ice from the NIR/SWIR1 band ratio (Huggel et al. 2004a, 2.2).

    Ice and snow are far brighter in NIR than SWIR1; water and rock are not.
    Combined with ESA's own snow/ice class, which catches ice the ratio misses
    in shadow.
    """
    ratio = idx.nir_swir1_ratio(scene.nir, scene.swir1)
    t = cfg.require("delineation.glacier_nir_swir1_ratio")
    with np.errstate(invalid="ignore"):
        m = (ratio > t) & scene.valid
    from src.watcher.scene import SCL_SNOW_ICE
    m |= (scene.scl == SCL_SNOW_ICE) & scene.valid
    # Remove speckle: a glacier is a contiguous body, not scattered pixels.
    return ndimage.binary_opening(m, structure=np.ones((3, 3)))


# Below this, there is no lake to assess. Every proxy here answers a question
# of the form "could mass reach THE LAKE" or "is THE DAM weak", and with no
# impounded water those questions are not merely unanswerable, they are
# malformed. Chamoli is the case that forces this: it holds 0.001 km2 of
# scattered meltwater, and without the guard every proxy fired on it, which
# would have reported a rock-and-ice avalanche as a glacial-lake hazard - the
# exact misattribution the negative control exists to catch.
MIN_LAKE_AREA_M2 = 5000.0


def compute_all(lake_meta: dict, scene, dem, lake_mask, cfg) -> dict:
    """Every proxy for one lake on one scene, as a structured hazard record."""
    res_m = float(np.sqrt(scene.pixel_area_m2))
    level = tr.lake_level(dem, lake_mask)
    glacier = glacier_mask(scene, cfg)
    area_m2 = float(lake_mask.sum() * scene.pixel_area_m2)

    if area_m2 < MIN_LAKE_AREA_M2:
        return {
            "lake_id": lake_meta["id"],
            "scene_label": scene.label,
            "scene_date": scene.acquired_date,
            "lake_area_m2": round(area_m2, 1),
            "lake_level_m": round(level, 1) if level is not None else None,
            "glacier_pixels": int(glacier.sum()),
            "dem_available": dem is not None,
            "no_lake": True,
            "no_lake_reason": (
                f"only {area_m2:,.0f} m2 of water found, below the "
                f"{MIN_LAKE_AREA_M2:,.0f} m2 minimum. No impounded water means no "
                "glacial-lake outburst hazard to assess; the dam-failure and "
                "mass-movement proxies are not applicable and are not computed. "
                "Steep terrain and avalanche sources may well be present - that "
                "is a different hazard, and calling it a GLOF hazard would be "
                "the misattribution this check exists to prevent."),
            "proxies": [],
            "proxies_fired": [],
            "n_fired": 0,
        }

    mg = mother_glacier(lake_mask, glacier, res_m, cfg)
    contact = bool(mg["fired"]) if mg["fired"] is not None else False

    proxies = [
        volume_band(area_m2, cfg),
        steep_lakefront_area(dem, lake_mask, res_m, level, cfg),
        *source_area_slopes(dem, lake_mask, glacier, res_m, level, cfg),
        mg,
        freeboard(dem, lake_mask, res_m, level, cfg, contact),
        distal_moraine_slope(dem, lake_mask, res_m, level, cfg),
        impulse_wave(dem, lake_mask, glacier, res_m, level, cfg),
        calving_onset(lake_mask, glacier, res_m, cfg, contact),
    ]

    # --- normalised, size-comparable quantities ---------------------------
    #
    # Absolute source areas are not comparable between a 0.04 km2 lake and a
    # 3.4 km2 one, and on the raw numbers the burst lakes actually score LOWER
    # than the PDGL lakes simply because they are smaller. What matters
    # physically for a displacement wave is the size of the potential mass
    # movement RELATIVE to the water it falls into: a 10e6 m3 detachment into a
    # 0.4e6 m3 lake is a very different proposition from the same detachment
    # into a 50e6 m3 lake. That ratio is the Thame geometry in one number.
    vb = next((p for p in proxies if p["proxy"] == "volume_band"), None)
    iw = next((p for p in proxies if p["proxy"] == "impulse_wave"), None)
    lake_vol = (vb["value"] or {}).get("central_m3") if vb and isinstance(vb["value"], dict) else None
    src_vol = iw["value"] if iw and isinstance(iw["value"], (int, float)) else None
    ratio = round(src_vol / lake_vol, 2) if (lake_vol and src_vol) else None
    proxies.append(_record(
        "source_to_lake_volume_ratio", ratio,
        bool(ratio is not None and ratio >= cfg.require(
            "proxies.impulse_wave.source_to_lake_volume_alarm")),
        cfg, "proxies.impulse_wave",
        {"estimated_source_volume_m3": src_vol,
         "lake_volume_central_m3": lake_vol,
         "alarm_threshold": cfg.require("proxies.impulse_wave.source_to_lake_volume_alarm"),
         "rationale": ("A displacement wave overtops a dam when the intruding "
                       "mass is large relative to the impounded water. Absolute "
                       "source area is not comparable across lake sizes; this "
                       "ratio is."),
         "confidence": "derived - inherits the volume-band error range and the "
                       "assumed release fraction"},
        tier="derived"))

    fired = [p["proxy"] for p in proxies if p["fired"]]
    return {
        "lake_id": lake_meta["id"],
        "scene_label": scene.label,
        "scene_date": scene.acquired_date,
        "lake_area_m2": round(area_m2, 1),
        "lake_level_m": round(level, 1) if level is not None else None,
        "glacier_pixels": int(glacier.sum()),
        "dem_available": dem is not None,
        "proxies": proxies,
        "proxies_fired": fired,
        "n_fired": len(fired),
    }
