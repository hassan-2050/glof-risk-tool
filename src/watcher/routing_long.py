"""Long-range corridor routing on the wide, coarse downstream DEM.

Stage 6 routes on the 7 km optical window, which caps every corridor at ~3.5 km
from the lake. This routes the same physics on `dem_downstream.tif` - a 100 km
box at 90 m - so a corridor can actually leave the headwaters.

WHAT IS THE SAME
    The Modified Single Flow descent, the lateral spread, and the reach-angle
    stop rule (Huggel et al. 2003). Changing the domain must not quietly change
    the model, or the comparison against Stage 6 means nothing.

WHAT IS DIFFERENT, AND WHY
  * 90 m cells, not 10 m. At 90 m a Himalayan gorge is one cell wide, so the
    corridor here is a FLOW PATH with an indicative buffer, not a width
    estimate. Stage 6 keeps the near-field geometry; this answers "how far, and
    past what".
  * Seeded from the lake's mapped outline projected onto the coarse grid, not
    re-delineated. Delineation is Stage 2's job and is done at 10 m.
  * Runs until the reach angle stops it, the flow leaves the domain, or a step
    budget is exhausted - whichever comes first, and it records which.

WHAT IT STILL CANNOT DO
    No hydraulics, no discharge, no depth, no timing. A corridor that exits the
    100 km box is still a lower bound; the flag just moves 14x further out.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

# Descent to the 8 neighbours, as (dr, dc, distance in cell units).
_NEIGHBOURS = [(-1, -1, math.sqrt(2)), (-1, 0, 1.0), (-1, 1, math.sqrt(2)),
               (0, -1, 1.0), (0, 1, 1.0),
               (1, -1, math.sqrt(2)), (1, 0, 1.0), (1, 1, math.sqrt(2))]


_NO_CENTRE = np.ones((3, 3), bool)
_NO_CENTRE[1, 1] = False


def _fill_pits(dem: np.ndarray, epsilon: float = 1e-3) -> np.ndarray:
    """Priority-flood depression fill (Barnes et al. 2014), with an epsilon tilt.

    Guarantees that every cell has a strictly descending path to the domain
    border, which is the property the router actually depends on.

    The previous implementation iterated a local minimum-of-neighbours fill a
    fixed 200 times. Two things were wrong with it. The footprint originally
    included the centre cell, so the pit test never fired at all. Once that was
    fixed it still only raised pits one layer per pass, so a basin deeper than
    200 layers stayed unfilled - South Lhonak's descent stalled after eight
    steps in a hollow the fill had not reached, and reported 0.87 km against an
    observed 60 km. A priority flood converges in one pass by construction.

    The epsilon tilt matters as much as the fill: a perfectly flat filled basin
    has no steepest-descent direction and a walk stalls on it. One millimetre is
    far below GLO-30's ~4 m vertical accuracy and restores a unique receiver.
    """
    import heapq

    z = dem.astype(np.float32, copy=True)
    finite = np.isfinite(z)
    if not finite.any():
        return np.zeros_like(z)
    # Voids are raised out of the way: an undeclared nodata cell must never
    # become the sink the whole domain drains into.
    z[~finite] = float(np.nanmax(z[finite]))

    h, w = z.shape
    closed = np.zeros((h, w), dtype=bool)
    heap: list[tuple[float, int, int]] = []
    for r in range(h):
        for c in (0, w - 1):
            heapq.heappush(heap, (float(z[r, c]), r, c))
            closed[r, c] = True
    for c in range(w):
        for r in (0, h - 1):
            if not closed[r, c]:
                heapq.heappush(heap, (float(z[r, c]), r, c))
                closed[r, c] = True

    while heap:
        zc, r, c = heapq.heappop(heap)
        for dr, dc, _ in _NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < h and 0 <= cc < w) or closed[rr, cc]:
                continue
            closed[rr, cc] = True
            if z[rr, cc] <= zc:
                z[rr, cc] = zc + epsilon
            heapq.heappush(heap, (float(z[rr, cc]), rr, cc))
    return z


def _spill_point(dem: np.ndarray, seed: np.ndarray, z: np.ndarray):
    """The cell where the lake's basin overflows: a priority-flood outlet.

    Returns the seed's lowest cell if the basin never spills inside the domain,
    so the caller always gets a usable start.
    """
    import heapq

    h, w = dem.shape
    surf = np.where(np.isfinite(dem), dem, z)
    seen = seed.copy()
    heap = []
    for r, c in zip(*np.where(seed)):
        for dr, dc, _ in _NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if 0 <= rr < h and 0 <= cc < w and not seen[rr, cc]:
                seen[rr, cc] = True
                heapq.heappush(heap, (float(surf[rr, cc]), int(rr), int(cc)))
    level = -np.inf
    while heap:
        zc, r, c = heapq.heappop(heap)
        if zc < level:
            return r, c                  # crossed the rim and started descending
        level = max(level, zc)
        for dr, dc, _ in _NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if 0 <= rr < h and 0 <= cc < w and not seen[rr, cc]:
                seen[rr, cc] = True
                heapq.heappush(heap, (float(surf[rr, cc]), int(rr), int(cc)))
    cells = list(zip(*np.where(seed)))
    return min(cells, key=lambda rc: z[rc[0], rc[1]])


def route_long(dem: np.ndarray, seed: np.ndarray, res_m: float,
               stop_reach_angle_deg: float, lateral_buffer_m: float,
               max_steps: int = 20000) -> dict:
    """Descend from `seed` until the reach angle stops the flow.

    The reach angle is measured from the lake surface to the current cell, the
    same H/L test Stage 6 uses: the flow is credible while
    (drop / horizontal distance) >= tan(stop angle), and stops where the slope
    of the line back to the source falls below it.
    """
    empty = {"corridor": np.zeros(dem.shape, dtype=bool), "cells": 0,
             "max_runout_m": 0.0, "reason": "no seed"}
    if not seed.any():
        return empty

    z = _fill_pits(dem)
    h, w = z.shape
    tan_stop = math.tan(math.radians(stop_reach_angle_deg))

    # TWO datums, two jobs - the D8 correction, restated on the coarse grid.
    #
    #   src_z   the ORIGINAL lake surface. The reach angle is measured from the
    #           water, so it must not inherit the pit fill.
    #   z_gate  the FILLED spill elevation. Routing must be allowed to leave at
    #           the rim; gating on the unfilled lake bottom blocks every
    #           neighbour, because filling raised the whole basin above it.
    #           Thame stopped 90 m from its own outlet on exactly this.
    src_z = float(np.nanmean(dem[seed]))
    z_gate = float(np.nanmax(z[seed]))
    # Distance from the seed, in metres, for the reach-angle denominator.
    dist = ndimage.distance_transform_edt(~seed, sampling=res_m)

    # Steepest descent down the channel, on the epsilon-filled surface.
    #
    # Two earlier attempts failed in opposite directions and both are worth
    # recording. A FIFO single-neighbour walk stalled at the first flat and
    # produced corridors SHORTER than the 7 km window. A priority-flood spanning
    # tree then flooded the entire sub-spill catchment: every lake reported the
    # same ~70.6 km straight line (the corner of the box), and following its
    # parent chain gave 150-352 km because a traversal tree meanders around a
    # catchment instead of running down a river. Steepest descent is what
    # actually traces a channel.
    path = np.zeros(dem.shape, dtype=bool)
    # FIRST find the spill point, THEN descend from it.
    #
    # A lake sits in a depression. Pit filling raises that whole depression to
    # its spill level, so from inside it every neighbour is higher or equal and
    # a steepest-descent walk is stuck on step zero - which is exactly what
    # happened to Thame and South Lhonak, both reporting 0.00 km while the
    # domain around them contained hundreds of thousands of cells that satisfy
    # the reach angle. The outlet is not adjacent to the lake; it is over the
    # rim. A priority flood on the ORIGINAL surface finds it: expand the lowest
    # frontier cell, tracking the highest elevation crossed so far, and the
    # first cell that comes in BELOW that level is where the basin spills.
    r, c = _spill_point(dem, seed, z)

    walk = [(r, c)]                    # the descent, in the order it happened
    run_along, reached_edge, steps = 0.0, False, 0
    max_run, straight_run = 0.0, 0.0
    while steps < max_steps:
        steps += 1
        best, best_slope, best_step = None, 0.0, 0.0
        for dr, dc, step in _NEIGHBOURS:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < h and 0 <= cc < w):
                reached_edge = True
                continue
            if path[rr, cc] or seed[rr, cc]:
                continue
            slope = (z[r, c] - z[rr, cc]) / (step * res_m)
            if slope > best_slope:
                best, best_slope, best_step = (rr, cc), slope, step
        if best is None:
            break                                   # nowhere lower to go
        r, c = best
        run_along += best_step * res_m
        path[r, c] = True
        walk.append((r, c))
        # Reach angle, source-to-here on the ORIGINAL surface. Recorded, not
        # used to break: the first cells out of the outlet routinely fail it,
        # because pit filling lets the walk cross ground whose true elevation is
        # at or above the lake, giving a negative drop. Breaking there stopped
        # three of four lakes at zero. The Fahrboeschung is a property of where
        # the deposit ENDS, so the runout is the furthest point that satisfies
        # it, and the walk continues past points that do not.
        straight = float(dist[r, c])
        if straight > 0 and (src_z - float(dem[r, c])) / straight >= tan_stop:
            max_run, straight_run = run_along, straight

    # The corridor is the walk up to the deposition limit, not the whole
    # walk: everything past max_run is where the flow would already have
    # stopped.
    if max_run > 0:
        path &= (dist <= straight_run)
        # The ordered walk, filtered by the SAME deposition limit as the mask,
        # so the polyline and the raster describe the same set of cells. The
        # order must come from here: sorting walked cells by distance from the
        # seed - the first implementation - interleaves vertices from
        # different bends of a meandering river, and Chamoli's 104 km channel
        # summed to 249 km of zigzag, putting Birahi at "202 km down-channel".
        walk = [(rr, cc) for rr, cc in walk if dist[rr, cc] <= straight_run]
    else:
        path[:] = False
        walk = []

    # Lateral spread: the flow path is a line on a 90 m grid; the corridor is
    # that line buffered, exactly as Stage 6 buffers its own path.
    if path.any() and lateral_buffer_m > 0:
        rad = max(1, int(round(lateral_buffer_m / res_m)))
        corridor = ndimage.binary_dilation(
            path, structure=np.ones((3, 3), bool), iterations=rad)
    else:
        corridor = path

    reason = ("left the domain" if reached_edge and steps < max_steps
              else "step budget exhausted" if steps >= max_steps
              else "reach angle")
    return {
        "corridor": corridor,
        "flow_path": path,
        "flow_walk": walk,
        "cells": int(corridor.sum()),
        "area_m2": round(float(corridor.sum()) * res_m * res_m, 1),
        "max_runout_m": round(max_run, 1),
        "straight_line_runout_m": round(straight_run, 1),
        "source_elevation_m": round(src_z, 1),
        "steps": steps,
        "truncated_at_domain_edge": bool(reached_edge),
        "stop_reason": reason,
        "parameters": {
            "model": "modified_single_flow (coarse-domain variant)",
            "stop_reach_angle_deg": stop_reach_angle_deg,
            "lateral_buffer_m": lateral_buffer_m,
            "dem_resolution_m": res_m,
            "source": "Huggel et al. 2003, NHESS 3:647",
        },
    }
