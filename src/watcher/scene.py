"""Scene loading and reflectance conversion.

One place where DN becomes reflectance, because getting that conversion wrong
is silent: the arrays still have the right shape, the indices still compute,
and the areas are simply wrong. Measured on our own pinned data, an
unconditional offset drives NDWI to 31200 on pre-2022 scenes while omitting it
drives the Dec-2023 Thyanbo scene to zero water pixels.

The 20 m bands (B11, SCL) are upsampled to the 10 m grid here rather than
downsampling the 10 m bands, because the lake is small: Thyanbo is ~44,000 m2,
which is ~440 pixels at 10 m but only ~110 at 20 m. Throwing away that
resolution to avoid an upsample would put us close to Sentinel-2's practical
limit for this lake.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling

from src.common.config import REPO_ROOT

# ESA quantification value: reflectance = (DN + BOA_ADD_OFFSET) / 10000
BOA_QUANTIFICATION = 10000.0

# Sentinel-2 Scene Classification (SCL) classes.
SCL_NODATA = 0
SCL_SATURATED = 1
SCL_DARK_AREA = 2          # includes topographic shadow
SCL_CLOUD_SHADOW = 3
SCL_VEGETATION = 4
SCL_BARE_SOIL = 5
SCL_WATER = 6
SCL_UNCLASSIFIED = 7
SCL_CLOUD_MEDIUM = 8
SCL_CLOUD_HIGH = 9
SCL_THIN_CIRRUS = 10
SCL_SNOW_ICE = 11


@dataclasses.dataclass
class Scene:
    """One acquisition over one lake window, on a single 10 m grid."""
    lake_id: str
    label: str
    acquired_date: str
    role: str
    green: np.ndarray          # B03 reflectance
    nir: np.ndarray            # B08 reflectance
    swir1: np.ndarray          # B11 reflectance, upsampled to 10 m
    scl: np.ndarray            # scene classification, upsampled to 10 m
    valid: np.ndarray          # bool: pixels with real data in every band
    transform: object
    crs: object
    pixel_area_m2: float
    boa_offset: float
    tile_cloud_pct: float
    solar_azimuth_deg: float | None
    solar_zenith_deg: float | None
    is_post_event: bool

    @property
    def shape(self) -> tuple[int, int]:
        return self.green.shape


def _to_reflectance(dn: np.ndarray, offset: float) -> np.ndarray:
    """DN -> surface reflectance, with nodata preserved as NaN.

    DN == 0 is ESA's nodata marker. Without masking it first, a nodata pixel
    with an offset applied becomes -0.1 reflectance, which is not obviously
    invalid and would quietly enter the index arithmetic.
    """
    out = dn.astype("float32")
    nodata = dn == 0
    out = (out + offset) / BOA_QUANTIFICATION
    out[nodata] = np.nan
    # Physically impossible values indicate a conversion error; clip rather
    # than propagate, but keep a small headroom above 1.0 for bright snow,
    # where legitimate reflectance can slightly exceed unity after correction.
    return np.clip(out, -0.1, 1.6)


def _resample_to(path: Path, shape: tuple[int, int], resampling: Resampling) -> np.ndarray:
    """Read a 20 m band onto the 10 m grid."""
    with rasterio.open(path) as src:
        return src.read(1, out_shape=shape, resampling=resampling)


def load_scene(lake_id: str, entry: dict) -> Scene | None:
    """Build a Scene from a manifest entry, or None if bands are missing."""
    assets = entry.get("assets") or {}
    needed = ("B03", "B08", "B11", "SCL")
    if not all(k in assets for k in needed):
        return None

    paths = {k: REPO_ROOT / assets[k]["path"] for k in needed}
    if not all(p.exists() for p in paths.values()):
        return None

    with rasterio.open(paths["B03"]) as src:
        green_dn = src.read(1)
        transform, crs = src.transform, src.crs
        px_area = abs(src.res[0] * src.res[1])
        shape = green_dn.shape
    with rasterio.open(paths["B08"]) as src:
        nir_dn = src.read(1)

    # Bilinear for the continuous reflectance band; NEAREST for SCL, because
    # interpolating class labels would invent classes that do not exist.
    swir_dn = _resample_to(paths["B11"], shape, Resampling.bilinear)
    scl = _resample_to(paths["SCL"], shape, Resampling.nearest)

    offset = entry.get("boa_add_offset")
    if offset is None:
        # Manifest predates the offset fix. Fall back to the processing
        # timestamp in the STAC id rather than guessing from acquisition date.
        tail = str(entry.get("stac_id", "")).rsplit("_", 1)[-1]
        offset = -1000.0 if (len(tail) >= 8 and tail[:8].isdigit()
                             and tail[:8] >= "20220125") else 0.0

    green = _to_reflectance(green_dn, offset)
    nir = _to_reflectance(nir_dn, offset)
    swir1 = _to_reflectance(swir_dn, offset)
    valid = ~(np.isnan(green) | np.isnan(nir) | np.isnan(swir1)) & (scl != SCL_NODATA)

    return Scene(
        lake_id=lake_id,
        label=entry["label"],
        acquired_date=entry["acquired_date"],
        role=entry["role"],
        green=green, nir=nir, swir1=swir1, scl=scl, valid=valid,
        transform=transform, crs=crs, pixel_area_m2=px_area,
        boa_offset=float(offset),
        tile_cloud_pct=float(entry.get("tile_cloud_cover_pct", float("nan"))),
        solar_azimuth_deg=entry.get("solar_azimuth_deg"),
        solar_zenith_deg=entry.get("solar_zenith_deg"),
        is_post_event=bool(entry.get("is_post_event", False)),
    )
