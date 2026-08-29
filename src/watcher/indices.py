"""Spectral indices, and the one fact about them that matters most.

NDSI and MNDWI are THE SAME FORMULA: (green - swir1) / (green + swir1). Snow
and water are both bright in green and dark in SWIR1, so MNDWI alone cannot
tell a frozen lake from an open one, and a snow-covered basin scores as water
across its whole extent. This is not a subtlety to note in the docs - it is the
single largest source of false area in a high-altitude Himalayan lake series,
and it is why the Dec-2023 Thyanbo scene delineated 4x its published area.

NIR is what separates them. Approximate surface reflectances at these
wavelengths:

                 green    NIR    SWIR1     NDWI    MNDWI/NDSI   NIR/SWIR1
  open water      0.08    0.02    0.01      0.60      0.78         ~2
  fresh snow      0.90    0.70    0.10      0.13      0.80         ~7
  glacier ice     0.60    0.45    0.08      0.14      0.76         ~6
  rock/soil       0.20    0.28    0.32     -0.17     -0.23         ~0.9

So water is the only class that is high in BOTH NDWI and MNDWI. Requiring both
rejects snow and ice, which single-index delineation cannot do. The NIR/SWIR1
ratio (Huggel et al. 2004a, threshold 2.2) is the third, independent check
specifically against glacier ice.
"""
from __future__ import annotations

import numpy as np


def _normalised_difference(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """(a - b) / (a + b), NaN where the denominator is degenerate.

    The guard matters: with the BOA offset applied, dark pixels can sum to
    almost exactly zero, and an unguarded ratio there produced NDWI values in
    the tens of thousands on our own data.
    """
    denom = a + b
    out = np.full(a.shape, np.nan, dtype="float32")
    ok = np.isfinite(denom) & (np.abs(denom) > 1e-4)
    out[ok] = (a[ok] - b[ok]) / denom[ok]
    return out


def ndwi(green: np.ndarray, nir: np.ndarray) -> np.ndarray:
    """McFeeters (1996). High for open water, low for snow and ice."""
    return _normalised_difference(green, nir)


def mndwi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """Xu (2006). High for water AND for snow/ice - never use it alone."""
    return _normalised_difference(green, swir1)


def ndsi(green: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """Normalised Difference Snow Index.

    Numerically identical to MNDWI; kept as a separate name because it is used
    for a different purpose (snow screening vs. water delineation) and merging
    them would hide the fact that a high value is ambiguous.
    """
    return _normalised_difference(green, swir1)


def nir_swir1_ratio(nir: np.ndarray, swir1: np.ndarray) -> np.ndarray:
    """Glacier-ice discriminator, Huggel et al. (2004a); threshold ~2.2.

    Ice and snow are far brighter in NIR than in SWIR1; water is dark in both.
    The floor on the denominator keeps deep-water pixels, where both bands
    approach zero, from producing a meaningless large ratio.
    """
    denom = np.where(np.isfinite(swir1), np.maximum(swir1, 1e-3), np.nan)
    return nir / denom


def hillshade(dem: np.ndarray, res_m: float, azimuth_deg: float,
              zenith_deg: float) -> np.ndarray:
    """Illumination in [0, 1] for the given solar geometry.

    Used to identify terrain shadow, which the imagery alone cannot distinguish
    from water: a shadowed slope and a lake are both dark in every band. The
    DEM plus sun angles is the only signal that separates them.
    """
    zy, zx = np.gradient(dem.astype("float64"), res_m)
    slope = np.arctan(np.hypot(zx, zy))
    # Aspect measured clockwise from north, matching the solar azimuth
    # convention in the Sentinel-2 metadata.
    aspect = np.arctan2(-zx, zy)
    az = np.radians(azimuth_deg)
    zen = np.radians(zenith_deg)
    illum = (np.cos(zen) * np.cos(slope)
             + np.sin(zen) * np.sin(slope) * np.cos(az - aspect))
    return np.clip(illum, 0.0, 1.0).astype("float32")
