"""Per-scene, per-lake quality assessment.

Stage 2's pass criteria require that every area estimate carries a QA flag, and
that a deliberately cloud/shadow-affected scene is FLAGGED rather than silently
mis-measured. So this module does not return a boolean; it returns the evidence
(which failure mode, over what fraction of the window) alongside a verdict, and
the delineator attaches the whole record to the area.

The failure modes handled are the ones the literature names for this setting:

  cloud            SCL 8/9/10. Obvious, and the one everyone already handles.
  cloud shadow     SCL 3. Dark, and easily read as water.
  terrain shadow   The dominant false positive in steep Himalayan valleys, and
                   the one the imagery CANNOT resolve alone - a shadowed slope
                   and a lake are both dark in every band. Needs the DEM and
                   solar geometry. SCL class 2 ("dark area pixels") catches
                   some of it but under-flags, so both signals are used.
  snow             SCL 11 plus a spectral test. Fresh snow scores as high as
                   water on MNDWI.
  frozen lake      Distinct from snow cover: the lake footprint itself is
                   high-MNDWI but low-NDWI. This is the failure that silently
                   shrinks an area series, because a frozen lake reads as
                   partially absent rather than absent.
  turbid water     Sediment raises NIR, pushing NDWI down toward the threshold,
                   so a real lake can be under-measured after a flood.
  small lake       Below a few hundred pixels, one boundary pixel is a
                   percentage point of area. Thyanbo at ~44,000 m2 is ~440
                   pixels at 10 m, so this is a live concern, not a formality.

Verdicts are ok / degraded / unusable. `degraded` means measure it but mark the
number; `unusable` means the area must not enter a trend or a screening
decision. Nothing is discarded silently - an unusable scene is still recorded
with its reason, because "we could not see the lake for six weeks before it
burst" is itself a finding.
"""
from __future__ import annotations

import numpy as np

from src.watcher import indices as idx
from src.watcher.scene import (SCL_CLOUD_HIGH, SCL_CLOUD_MEDIUM, SCL_CLOUD_SHADOW,
                               SCL_DARK_AREA, SCL_SNOW_ICE, SCL_THIN_CIRRUS, Scene)

VERDICT_OK = "ok"
VERDICT_DEGRADED = "degraded"
VERDICT_UNUSABLE = "unusable"


def assess(scene: Scene, cfg, dem: np.ndarray | None = None,
           lake_mask: np.ndarray | None = None) -> dict:
    """Build the QA record for one scene.

    `lake_mask` is the provisional water mask; when supplied, the frozen-lake
    and turbidity tests run over the lake footprint rather than the whole
    window, which is the only place they mean anything.
    """
    q = cfg.require("delineation.qa")
    valid = scene.valid
    n_valid = int(valid.sum())
    if n_valid == 0:
        return {"verdict": VERDICT_UNUSABLE, "reasons": ["no_valid_pixels"],
                "fractions": {}, "checks": {}}

    def frac(mask: np.ndarray) -> float:
        return float((mask & valid).sum()) / n_valid

    scl = scene.scl
    cloud = np.isin(scl, [SCL_CLOUD_MEDIUM, SCL_CLOUD_HIGH, SCL_THIN_CIRRUS])
    cloud_shadow = scl == SCL_CLOUD_SHADOW
    dark_area = scl == SCL_DARK_AREA
    snow_scl = scl == SCL_SNOW_ICE

    fractions = {
        "cloud": frac(cloud),
        "cloud_shadow": frac(cloud_shadow),
        "scl_dark_area": frac(dark_area),
        "snow_scl": frac(snow_scl),
    }

    # --- terrain shadow, from DEM + solar geometry -------------------------
    checks: dict = {}
    terrain_shadow_frac = None
    if dem is not None and scene.solar_azimuth_deg is not None \
            and scene.solar_zenith_deg is not None and dem.shape == scene.shape:
        illum = idx.hillshade(dem, np.sqrt(scene.pixel_area_m2),
                              float(scene.solar_azimuth_deg),
                              float(scene.solar_zenith_deg))
        shadowed = illum < q["terrain_shadow_illum_min"]
        terrain_shadow_frac = frac(shadowed)
        checks["terrain_shadow_source"] = "dem_hillshade"
        checks["mean_illumination"] = float(np.nanmean(illum[valid]))
    else:
        # Fall back to SCL's dark-area class, and say so. It under-flags
        # topographic shadow, so a fallback verdict is weaker evidence.
        terrain_shadow_frac = fractions["scl_dark_area"]
        checks["terrain_shadow_source"] = "scl_dark_area_fallback"
        checks["fallback_reason"] = (
            "no DEM on grid" if dem is None or dem.shape != scene.shape
            else "solar geometry absent from manifest")
    fractions["terrain_shadow"] = terrain_shadow_frac

    # --- snow, spectrally ---------------------------------------------------
    ndsi_a = idx.ndsi(scene.green, scene.swir1)
    ndwi_a = idx.ndwi(scene.green, scene.nir)
    with np.errstate(invalid="ignore"):
        snow_spectral = (ndsi_a > q["snow_index_max"]) & (ndwi_a < 0.20) & valid
    fractions["snow_spectral"] = frac(snow_spectral)

    # --- frozen lake, over the lake footprint only --------------------------
    if lake_mask is not None and lake_mask.any():
        with np.errstate(invalid="ignore"):
            frozen_px = lake_mask & (ndsi_a > q["snow_index_max"]) & (ndwi_a < 0.20)
        frozen_fraction = float(frozen_px.sum()) / float(lake_mask.sum())
        checks["frozen_fraction_of_lake"] = frozen_fraction
        # Turbidity: sediment lifts NIR, dragging NDWI toward the threshold.
        lake_ndwi = ndwi_a[lake_mask]
        lake_ndwi = lake_ndwi[np.isfinite(lake_ndwi)]
        if lake_ndwi.size:
            checks["lake_ndwi_median"] = float(np.median(lake_ndwi))
            checks["lake_ndwi_p25"] = float(np.percentile(lake_ndwi, 25))
    else:
        frozen_fraction = 0.0

    # --- verdict ------------------------------------------------------------
    reasons: list[str] = []
    verdict = VERDICT_OK
    cloud_ceiling = q["cloud_prob_max"] / 100.0

    contaminated = fractions["cloud"] + fractions["cloud_shadow"]
    if contaminated > cloud_ceiling:
        verdict = VERDICT_UNUSABLE
        reasons.append(f"cloud+shadow {contaminated:.0%} over window "
                       f"exceeds {cloud_ceiling:.0%}")
    elif contaminated > cloud_ceiling / 2:
        verdict = VERDICT_DEGRADED
        reasons.append(f"cloud+shadow {contaminated:.0%} over window")

    if fractions["terrain_shadow"] > 0.5:
        verdict = VERDICT_UNUSABLE
        reasons.append(f"terrain shadow over {fractions['terrain_shadow']:.0%} "
                       f"of window ({checks['terrain_shadow_source']})")
    elif fractions["terrain_shadow"] > 0.25 and verdict == VERDICT_OK:
        verdict = VERDICT_DEGRADED
        reasons.append(f"terrain shadow {fractions['terrain_shadow']:.0%} of window")

    if frozen_fraction > 0.5:
        verdict = VERDICT_UNUSABLE
        reasons.append(f"lake surface {frozen_fraction:.0%} frozen or snow-covered; "
                       "area would be under-measured")
    elif frozen_fraction > 0.2 and verdict != VERDICT_UNUSABLE:
        verdict = VERDICT_DEGRADED
        reasons.append(f"lake surface {frozen_fraction:.0%} frozen or snow-covered")

    if fractions["snow_spectral"] > 0.75 and verdict == VERDICT_OK:
        verdict = VERDICT_DEGRADED
        reasons.append(f"basin {fractions['snow_spectral']:.0%} snow-covered; "
                       "elevated risk of snow being counted as water")

    return {
        "verdict": verdict,
        "reasons": reasons,
        "fractions": {k: round(v, 4) for k, v in fractions.items()},
        "checks": checks,
        "valid_pixels": n_valid,
    }


def usability_score(qa: dict) -> float:
    """Rank scenes for the 'best scene per year' choice.

    Higher is better. Combines the failure modes that actually cost us area
    accuracy; used where more than one scene exists for a year, per the Stage 2
    task to rank on clarity and low snow rather than trusting tile metadata.
    """
    f = qa.get("fractions", {})
    penalty = (2.0 * f.get("cloud", 0.0)
               + 2.0 * f.get("cloud_shadow", 0.0)
               + 1.0 * f.get("terrain_shadow", 0.0)
               + 1.5 * qa.get("checks", {}).get("frozen_fraction_of_lake", 0.0)
               + 0.5 * f.get("snow_spectral", 0.0))
    if qa.get("verdict") == VERDICT_UNUSABLE:
        penalty += 10.0
    return -penalty
