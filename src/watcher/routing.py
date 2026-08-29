"""Stage 6: Modified Single Flow routing to an indicative inundation corridor.

Implements Huggel et al. (2003, NHESS 3:647): propagate downslope from the lake
outlet and stop where the average slope from the SOURCE - not the local slope -
falls to 11 degrees (tan alpha ~ 0.19) for a debris flow, or ~3 degrees for a
clear-water flood, which travels far further.

What this is NOT: a flood model. There is no hydraulics, no volume routing, no
roughness. On a 30 m DSM in a valley 50 m wide the channel is one to two pixels
across and its cross-section is unresolved. The output is an indicative
corridor and every record says so in structured metadata, not in a caption
someone can crop out.

Three corrections over the obvious implementation, each forced by a measured
failure on the pinned DEMs rather than anticipated:

1. The outlet is the lowest rim cell WITH a downhill escape, found on the
   original surface. Using a depression-filled surface put the Thyanbo outlet
   20 m ABOVE the water line, because filling raises the rim to the basin's
   spill point - but a GLOF escapes by breaching its dam, not by overtopping a
   20 m sill.

2. Propagation follows the drainage without a per-step directional gate.
   Testing each step against the local steepest-descent direction rejected
   legitimate downstream cells, because on a 30 m DSM that direction is noise:
   the same terrain routes 3.9 km with 390 m of drop once the test is removed.
   MSF lateral spread is applied instead as a distance buffer on the result.

3. The reach angle truncates the finished path; it does not gate propagation.
   Applied per step it silently becomes a local-slope rule and stops the flow
   at the first gentle reach - Thyanbo falls only 7.5 degrees over its first
   190 m, so every corridor died at 200 m.
"""
from __future__ import annotations

import heapq
import math

import numpy as np
from scipy import ndimage
from skimage.morphology import reconstruction

_NEIGHBOURS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

# Cap on how far depression filling may raise a cell: enough to bridge DSM
# speckle, far too little to flood the lake basin and relocate the outlet.
MAX_FILL_M = 5.0
# Slack for the flat ties that filling leaves behind.
FLAT_TOLERANCE_M = 0.01


def fill_depressions(dem: np.ndarray) -> np.ndarray:
    """Priority-flood depression filling by morphological reconstruction.

    Steepest descent is undefined inside a pit, and a 30 m DSM of Himalayan
    terrain is full of them, both real and spurious. Reconstruction by erosion
    floods each closed basin to its spill point. Used only to decide WHERE flow
    goes; the original elevations are kept for the reach-angle test, which
    decides HOW FAR it travels.
    """
    finite = np.isfinite(dem)
    if not finite.any():
        return dem
    work = np.where(finite, dem, np.nanmax(dem[finite])).astype("float64")
    seed = np.full(work.shape, work.max(), dtype="float64")
    seed[0, :] = work[0, :]
    seed[-1, :] = work[-1, :]
    seed[:, 0] = work[:, 0]
    seed[:, -1] = work[:, -1]
    filled = reconstruction(seed, work, method="erosion")
    return np.where(finite, filled, np.nan)


def find_outlet(dem: np.ndarray, lake: np.ndarray) -> tuple[int, int] | None:
    """The spill point: the lowest rim cell that has a downhill escape.

    Not simply the lowest shoreline cell. A moraine-dammed lake is impounded by
    ground standing above the water, so the lowest point on its shoreline is
    typically on the UPSTREAM side where the valley runs into the lake.
    Measured on Thyanbo: the lowest ring cell sits at 4,639.8 m with all three
    of its non-lake neighbours higher, so routing from it had nowhere to go.
    """
    if dem is None or not lake.any():
        return None
    ring = ndimage.binary_dilation(lake, structure=np.ones((3, 3))) & ~lake
    ring &= np.isfinite(dem)
    if not ring.any():
        return None

    h, w = dem.shape
    best = None
    for y, x in zip(*np.where(ring)):
        z_c = float(dem[y, x])
        for dy, dx in _NEIGHBOURS:
            ny, nx = y + dy, x + dx
            if not (0 <= ny < h and 0 <= nx < w):
                continue
            if lake[ny, nx] or not np.isfinite(dem[ny, nx]):
                continue
            z_n = float(dem[ny, nx])
            if z_n >= z_c:
                continue                      # no downhill escape this way
            sill = max(z_c, z_n)              # water must clear both
            if best is None or sill < best[0]:
                best = (sill, int(y), int(x))
    if best is None:
        return None
    return best[1], best[2]


def msf_corridor(dem: np.ndarray, lake: np.ndarray, res_m: float, cfg,
                 clearwater: bool = False) -> dict:
    """Route from the lake's rim; return the corridor mask and diagnostics."""
    stop_angle = cfg.require("routing.clearwater_reach_angle_deg" if clearwater
                             else "routing.stop_reach_angle_deg")
    spread_m = cfg.require("routing.lateral_buffer_m")
    tan_stop = math.tan(math.radians(stop_angle))
    empty = {"corridor": np.zeros_like(lake), "outlet": None, "cells": 0,
             "area_m2": 0.0, "max_runout_m": 0.0}

    if dem is None or not lake.any():
        return {**empty, "reason": "no DEM or no lake"}

    # Three surfaces, three jobs, and mixing them up cost several rounds:
    #   dem          original - finds the OUTLET and measures the REACH ANGLE
    #   routing_dem  fully filled - decides WHERE flow goes
    # Capping the fill (an earlier attempt) kept the outlet honest but left the
    # ~30 m Thyanbo basin unfilled, so descent stalled inside it and every
    # corridor came back with a total drop of zero. Full filling is correct for
    # routing precisely because it floods the basin; the outlet is protected by
    # being found on the original surface instead.
    routing_dem = fill_depressions(dem)

    # Seed from the WHOLE rim, not one chosen outlet cell.
    #
    # Picking a single spill cell proved hopeless: a 10 m optical lake mask
    # meets a 30 m DSM, so the rim elevations are noisy, and the "lowest cell
    # with a downhill escape" landed in a one-pixel local dip whose own spill
    # ran back uphill. Descent from it reached 281 cells and 149 m while the
    # valley below fell 390 m over 3.9 km. Releasing the flood from every rim
    # cell at once removes the need to know exactly where the dam breaches -
    # which we cannot know from a DSM anyway - and lets the drainage decide.
    rim = ndimage.binary_dilation(lake, structure=np.ones((3, 3))) & ~lake
    rim &= np.isfinite(routing_dem)
    if not rim.any():
        return {**empty, "reason": "lake has no rim inside the analysis window"}

    # The reach angle is measured from the LAKE SURFACE, which is the head of
    # water available to drive the flood, not from whichever rim pixel the DSM
    # happens to make lowest.
    lake_elev = dem[lake]
    lake_elev = lake_elev[np.isfinite(lake_elev)]
    if not lake_elev.size:
        return {**empty, "reason": "no valid DEM values over the lake"}
    z0 = float(np.median(lake_elev))
    h, w = dem.shape

    # --- descent over the drainage, no directional gate --------------------
    dist = np.full(dem.shape, np.inf, dtype="float64")
    heap = []
    for ry, rx in zip(*np.where(rim)):
        dist[ry, rx] = 0.0
        heap.append((0.0, int(ry), int(rx)))
    heapq.heapify(heap)
    oy, ox = int(np.where(rim)[0][0]), int(np.where(rim)[1][0])
    while heap:
        d, y, x = heapq.heappop(heap)
        if d > dist[y, x]:
            continue
        z_here = float(routing_dem[y, x])
        for dy, dx in _NEIGHBOURS:
            ny, nx = y + dy, x + dx
            if not (0 <= ny < h and 0 <= nx < w):
                continue
            if lake[ny, nx] or not np.isfinite(routing_dem[ny, nx]):
                continue
            if float(routing_dem[ny, nx]) > z_here + FLAT_TOLERANCE_M:
                continue
            nd = d + math.hypot(dy, dx) * res_m
            if nd < dist[ny, nx]:
                dist[ny, nx] = nd
                heapq.heappush(heap, (nd, ny, nx))

    reached = np.isfinite(dist)
    if reached.sum() <= int(rim.sum()):
        return {**empty, "outlet": None,
                "reason": "no descending drainage leaves the lake rim within this window"}

    # --- reach-angle truncation, on ORIGINAL elevations --------------------
    # The reach angle defines the TERMINUS, not a per-cell mask.
    #
    # Masking every cell that fails the test disconnects the corridor: near the
    # outlet the flow has travelled 20-100 m and dropped almost nothing, so
    # those cells fail, and cutting them severs the far reaches that pass
    # easily. The corridor then collapsed to a 281-cell puddle with zero total
    # drop while the drainage below it fell 390 m over 3.9 km.
    #
    # The physical statement is "the flow runs out at the distance where the
    # average gradient from source can no longer sustain it", so we take the
    # furthest distance still meeting the criterion and keep everything the
    # flow passes through on the way.
    with np.errstate(divide="ignore", invalid="ignore"):
        reach_tan = np.where(reached, (z0 - dem) / np.maximum(dist, res_m), -np.inf)
    qualifying = reached & (reach_tan >= tan_stop)
    runout_limit = float(dist[qualifying].max()) if qualifying.any() else 0.0
    within = reached & (dist <= runout_limit) & ~rim
    lbl, nlab = ndimage.label(within | rim)
    if nlab:
        keep = set(np.unique(lbl[rim])) - {0}
        within = np.isin(lbl, list(keep)) & within

    # --- MSF lateral spread, as a distance ---------------------------------
    buf_px = max(1, int(round(spread_m / res_m)))
    corridor = ndimage.binary_dilation(
        within, structure=np.ones((3, 3)), iterations=buf_px) & reached & ~lake

    d_in = dist[corridor]
    max_runout = float(d_in[np.isfinite(d_in)].max()) if corridor.any() else 0.0
    px_area = res_m * res_m
    reached_edge = bool(corridor[0, :].any() or corridor[-1, :].any()
                        or corridor[:, 0].any() or corridor[:, -1].any())
    min_z = float(np.nanmin(dem[corridor])) if corridor.any() else None

    return {
        "corridor": corridor,
        "outlet": {"seeded_from": "entire lake rim", "rim_cells": int(rim.sum()),
                   "lake_surface_elevation_m": round(z0, 1)},
        "cells": int(corridor.sum()),
        "area_m2": round(float(corridor.sum() * px_area), 1),
        "max_runout_m": round(max_runout, 1),
        "min_elevation_reached_m": round(min_z, 1) if min_z is not None else None,
        "total_drop_m": round(z0 - min_z, 1) if min_z is not None else None,
        "drainage_cells_available": int(reached.sum()),
        "cells_within_reach_angle": int(within.sum()),
        "runout_limit_m": round(runout_limit, 1),
        "truncated_at_window_edge": reached_edge,
        "parameters": {
            "model": "modified_single_flow",
            "regime": "clearwater_flood" if clearwater else "debris_flow",
            "stop_reach_angle_deg": stop_angle,
            "lateral_buffer_m": spread_m,
            "dem_resolution_m": round(res_m, 1),
            "source": "Huggel et al. 2003, NHESS 3:647",
        },
        "disclaimer": {
            "id": cfg.require("routing.disclaimer_id"),
            "text": ("INDICATIVE CORRIDOR, NOT A FLOOD MAP. Derived from a 30 m "
                     "DSM with a reach-angle stop rule and no hydraulics. In "
                     "narrow Himalayan valleys the channel is one to two pixels "
                     "wide and its cross-section is unresolved, the binding "
                     "accuracy constraint documented for both LAHARZ and "
                     "r.avaflow on free DEMs. Screening and exposure triage only."),
            "truncated_note": ("Corridor reaches the edge of the analysis window, "
                               "so the runout length is a LOWER BOUND."
                               if reached_edge else None),
        },
    }


def laharz_cross_check(volume_m3: float, cfg) -> dict:
    """LAHARZ-style statistical planimetric area, B = c * V^(2/3).

    A second opinion from an entirely different basis - an empirical scaling
    law rather than a routed path. Where the two disagree sharply that is
    information about confidence, not an error to reconcile away.
    """
    if not volume_m3 or volume_m3 <= 0:
        return {"applicable": False, "reason": "no volume estimate"}
    c = cfg.require("routing.laharz_coefficient")
    area = c * volume_m3 ** (2.0 / 3.0)
    return {
        "applicable": True,
        "planimetric_area_m2": round(area, 1),
        "coefficient": c,
        "source": "Schilling 2014 (LAHARZ), debris-flow coefficient",
        "confidence_tier": "moderate",
        "caveat": ("Statistical relation calibrated on volcanic debris flows, "
                   "applied to a GLOF volume band that itself carries 50 to "
                   ">400% error. An order-of-magnitude check on the routed "
                   "corridor, not an independent measurement."),
    }
