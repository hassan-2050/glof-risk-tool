"""Terrain analysis on the DEM: slope, depression angle, reach angle, distance.

Everything Stage 4 needs that is geometry rather than hazard interpretation.
Kept separate so the proxies read as the published criteria they implement
rather than as array arithmetic.

The binding constraint throughout is that Copernicus GLO-30 is a ~30 m DSM.
That is fine for slope statistics over a 1 km buffer and hopeless for a moraine
crest a few pixels wide, so freeboard and distal-slope outputs carry lower
confidence than the slope-based proxies, and say so in their own records.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def pixel_size_m(transform) -> float:
    return float(abs(transform.a))


def slope_deg(dem: np.ndarray, res_m: float) -> np.ndarray:
    """Terrain slope in degrees.

    np.gradient uses central differences, which over a 30 m DSM smooths across
    ~90 m. That under-reads the very steepest faces, so avalanche-source slopes
    here are conservative - a real 60 degree face may measure 50. Stated rather
    than corrected, because the published thresholds were themselves derived
    from comparable DEMs.
    """
    gy, gx = np.gradient(dem.astype("float64"), res_m)
    return np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")


def distance_to_m(mask: np.ndarray, res_m: float) -> np.ndarray:
    """Euclidean distance in metres from every pixel to the nearest True."""
    if not mask.any():
        return np.full(mask.shape, np.inf, dtype="float32")
    return (ndimage.distance_transform_edt(~mask) * res_m).astype("float32")


def depression_angle(dem: np.ndarray, lake: np.ndarray, res_m: float,
                     lake_level_m: float) -> np.ndarray:
    """Angle from the lake surface up to each surrounding terrain pixel.

    tan(angle) = (elevation - lake level) / horizontal distance to the lake.
    This is the quantity Fujita et al. (2013) threshold at 10 degrees to define
    Steep Lakefront Area: terrain that is both high AND close is what delivers
    mass into the water.
    """
    dist = distance_to_m(lake, res_m)
    rise = dem.astype("float32") - float(lake_level_m)
    with np.errstate(divide="ignore", invalid="ignore"):
        ang = np.degrees(np.arctan(rise / np.maximum(dist, res_m)))
    ang[~np.isfinite(ang)] = np.nan
    return ang


def reach_angle_to(dem: np.ndarray, target: np.ndarray, res_m: float,
                   target_level_m: float) -> np.ndarray:
    """Reach angle (alpha) from each pixel down to the target.

    tan(alpha) = drop / runout. The travel-distance criterion used throughout
    the mass-movement literature: a source can reach the lake if its reach
    angle exceeds the process threshold (17 degrees for avalanches, 20 for
    rockfall, 14 for the impulse-wave criterion of Allen et al. 2019).

    Identical arithmetic to depression_angle but stated separately because the
    direction of reasoning is opposite - here we ask what can arrive, there
    what overlooks.
    """
    dist = distance_to_m(target, res_m)
    drop = dem.astype("float32") - float(target_level_m)
    with np.errstate(divide="ignore", invalid="ignore"):
        ang = np.degrees(np.arctan(drop / np.maximum(dist, res_m)))
    ang[~np.isfinite(ang)] = np.nan
    return ang


def shoreline(lake: np.ndarray) -> np.ndarray:
    """One-pixel ring just outside the lake."""
    if not lake.any():
        return np.zeros_like(lake)
    return ndimage.binary_dilation(lake, structure=np.ones((3, 3))) & ~lake


def lake_level(dem: np.ndarray, lake: np.ndarray) -> float | None:
    """Lake surface elevation, as the median over the water pixels.

    Median rather than minimum: a 30 m DSM over water contains speckle, and the
    minimum would systematically pick the worst pixel in the lake.
    """
    if dem is None or not lake.any():
        return None
    v = dem[lake]
    v = v[np.isfinite(v)]
    return float(np.median(v)) if v.size else None


def fetch_m(lake: np.ndarray, res_m: float) -> float:
    """Longest straight-line dimension of the lake, in metres.

    Sakai et al. (2009) relate calving onset to fetch, the distance over which
    wind can drive waves against the ice cliff. Approximated here by the
    maximum extent of the lake polygon, which is an upper bound on fetch in any
    single direction.
    """
    if not lake.any():
        return 0.0
    ys, xs = np.where(lake)
    return float(max(ys.max() - ys.min() + 1, xs.max() - xs.min() + 1) * res_m)


def largest_region_area_m2(mask: np.ndarray, res_m: float) -> tuple[float, int]:
    """Area of the largest connected region, and how many regions there are."""
    if not mask.any():
        return 0.0, 0
    labels, n = ndimage.label(mask)
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    return float(sizes.max() * res_m * res_m), int(n)
