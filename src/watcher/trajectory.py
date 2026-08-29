"""Stage 3: multi-date trajectory and post-hoc burst detection.

Two jobs, and the second one has a trap in it.

TRAJECTORY. A two-date delta is a brittle statistic: it depends entirely on
which two dates you picked, and on this data one of them is often partially
frozen. The trend is therefore fitted with Theil-Sen rather than least squares,
because a single bad area estimate moves an OLS slope a long way and Theil-Sen
barely notices - it takes the median of all pairwise slopes, tolerating up to
~29% corrupted points. On a nine-point series with two frozen readings, that
difference is the whole ballgame.

BURST DETECTION. A sudden drop in lake area is the signature of an outburst.
It is ALSO the signature of a lake freezing over, because our delineation
measures open water. Those two are not distinguishable by area alone: South
Lhonak lost 15.38% of its area to a real outburst, while Thyanbo appears to
lose 65% between October and December simply by icing up. A detector that only
watches area would fire every winter on every high lake and be useless.

So a drop is only reported when the lake is still OPEN on the later date - the
QA open-water fraction from Stage 2 is what separates "the water left" from
"the water froze". This is the single most important guard in the stage, and it
is why Stage 2 computes that fraction against a reference footprint rather than
against each scene's own mask.
"""
from __future__ import annotations

import datetime as dt
import itertools

import numpy as np


def _date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def usable_points(lake_result: dict, cfg, include_event: bool = True) -> list[dict]:
    """Observations good enough to carry a trend or a drop.

    An unusable scene is not silently dropped; it is excluded here and counted
    in the output, because "we could not see this lake for two years" is a
    finding about monitoring capability, not an absence of data.
    """
    min_open = cfg.require("trajectory.min_open_water_fraction")
    pts = []
    for s in lake_result.get("scenes", []):
        if s["role"] == "qa_hard":
            continue
        if not include_event and s["role"] != "annual":
            continue
        verdict = s["qa"]["verdict"]
        open_frac = s.get("footprint_open_water_fraction")
        pts.append({
            "date": s["acquired_date"],
            "label": s["label"],
            "role": s["role"],
            "is_post_event": s["is_post_event"],
            "area_m2": s["area_m2"],
            "area_km2": s["area_km2"],
            "qa_verdict": verdict,
            "open_water_fraction": open_frac,
            "usable": verdict != "unusable" and (open_frac is None or open_frac >= min_open),
        })
    pts.sort(key=lambda p: (p["date"], p["label"]))
    return pts


def theil_sen_slope(dates: list[dt.date], values: list[float]) -> tuple[float, float]:
    """Robust slope (units/year) and its median absolute deviation.

    Median of all pairwise slopes. Chosen over least squares because a frozen
    or cloud-clipped area estimate is a large, one-sided outlier and OLS has a
    breakdown point of zero.
    """
    slopes = []
    for (d1, v1), (d2, v2) in itertools.combinations(zip(dates, values), 2):
        dt_years = (d2 - d1).days / 365.25
        if abs(dt_years) > 1e-6:
            slopes.append((v2 - v1) / dt_years)
    if not slopes:
        return float("nan"), float("nan")
    arr = np.array(slopes, dtype="float64")
    med = float(np.median(arr))
    return med, float(np.median(np.abs(arr - med)))


def trend_features(points: list[dict], cfg) -> dict:
    """Growth-rate features over the usable annual observations."""
    min_n = cfg.require("trajectory.min_series_length")
    usable = [p for p in points if p["usable"] and p["role"] == "annual"]
    n = len(usable)
    base = {
        "n_annual_observations": len([p for p in points if p["role"] == "annual"]),
        "n_usable": n,
        "sufficient": n >= min_n,
    }
    if n < min_n:
        base["note"] = (f"only {n} usable annual observations (need {min_n}); "
                        "no trend reported rather than a trend from too few points")
        return base

    dates = [_date(p["date"]) for p in usable]
    areas = [p["area_m2"] for p in usable]
    slope, mad = theil_sen_slope(dates, areas)
    span_years = (dates[-1] - dates[0]).days / 365.25
    first, last = areas[0], areas[-1]

    base.update({
        "first_date": usable[0]["date"], "last_date": usable[-1]["date"],
        "span_years": round(span_years, 2),
        "first_area_m2": first, "last_area_m2": last,
        "theil_sen_slope_m2_per_year": round(slope, 1),
        "theil_sen_slope_mad": round(mad, 1),
        # Growth relative to the median area, not to the first observation. The
        # first point is one noisy measurement, and dividing by it lets a single
        # bad reading dominate the headline growth figure.
        "median_area_m2": round(float(np.median(areas)), 1),
        "relative_growth_pct_per_year": (
            round(100.0 * slope / float(np.median(areas)), 2)
            if np.median(areas) > 0 else None),
        # Kept for comparison with the naive baseline in Stage 7, and clearly
        # labelled as the brittle statistic it is.
        "naive_two_date_change_pct": (round(100.0 * (last - first) / first, 2)
                                      if first > 0 else None),
    })
    return base


def detect_drops(points: list[dict], cfg) -> list[dict]:
    """Sudden area losses that look like outbursts rather than seasonal ice.

    Three tests, each added because the previous set produced a specific wrong
    answer on the pinned data:

    1. MAGNITUDE - the drop exceeds the configured fraction. On its own this
       fired on three non-burst lakes.

    2. SUDDENNESS - the two observations are close enough in time to describe
       one event. A GLOF drains a lake in hours; a 12% loss across 390 days
       (Thulagi) or 29% across 732 days (Imja) is interannual variation with a
       sampling gap in the middle, and calling it a burst is a category error.

    3. PERSISTENCE - the lake does not refill. This is the test that separates
       a real outburst from autumn freeze-up, and neither magnitude nor open
       water fraction can do it: Tsho Rolpa lost 32% between October and
       December 2024 with 65% open water, while Thyanbo lost 60% across the
       real 16 Aug 2024 outburst with 62% open water. Almost identical
       signatures. The difference only shows up later - Tsho Rolpa comes back
       in the spring and Thyanbo never does, because its dam is gone.

    Suppressed candidates are kept in the output with their reason. A detector
    that silently discards is indistinguishable from one that never noticed.
    """
    frac = cfg.require("trajectory.sudden_drop_fraction")
    min_area_km2 = cfg.require("trajectory.sudden_drop_min_area_km2")
    min_open = cfg.require("trajectory.min_open_water_fraction")
    max_days = cfg.require("trajectory.max_days_between_observations")
    recovery_frac = cfg.require("trajectory.recovery_fraction")
    recovery_days = cfg.require("trajectory.recovery_window_days")

    events = []
    usable = [p for p in points if p["usable"]]
    for i, (prev, curr) in enumerate(zip(usable, usable[1:])):
        if prev["area_km2"] < min_area_km2 or prev["area_m2"] <= 0:
            continue
        drop = (prev["area_m2"] - curr["area_m2"]) / prev["area_m2"]
        if drop < frac:
            continue

        days = (_date(curr["date"]) - _date(prev["date"])).days
        later_open = curr["open_water_fraction"]

        reasons = []
        if days > max_days:
            reasons.append(
                f"observations {days} days apart, beyond the {max_days}-day limit; "
                "too far apart to attribute to a single sudden event")
        if later_open is not None and later_open < min_open:
            reasons.append(
                f"lake only {later_open:.0%} open water on {curr['date']}; the "
                f"{100*drop:.0f}% loss is consistent with freeze-up, not drainage")

        # Persistence: does any later observation inside the recovery window
        # come back to near the pre-drop area?
        #
        # Absence of evidence is not evidence of absence. If no USABLE
        # observation follows, we cannot tell a drained lake from a frozen one,
        # and the honest answer is "unconfirmed" rather than a burst. Treating
        # no-follow-up as no-recovery fired on Tsho Rolpa's Oct-to-Dec 2024
        # freeze-up purely because its 2025 scenes were themselves frozen and
        # therefore unusable - the detector was reading its own blind spot as
        # a positive.
        recovery = None
        follow_ups = 0
        for later in usable[i + 2:]:
            gap = (_date(later["date"]) - _date(curr["date"])).days
            if gap > recovery_days:
                break
            follow_ups += 1
            if later["area_m2"] >= recovery_frac * prev["area_m2"]:
                recovery = {"date": later["date"], "area_m2": later["area_m2"],
                            "days_after": gap,
                            "fraction_of_pre_drop": round(later["area_m2"] / prev["area_m2"], 3)}
                break
        if recovery:
            reasons.append(
                f"lake recovered to {recovery['fraction_of_pre_drop']:.0%} of its "
                f"pre-drop area by {recovery['date']} ({recovery['days_after']} days "
                "later); a drained lake does not refill, a frozen one thaws")

        confirmed_persistent = follow_ups > 0 and recovery is None
        unconfirmed = not reasons and follow_ups == 0

        events.append({
            "from_date": prev["date"], "to_date": curr["date"],
            "from_label": prev["label"], "to_label": curr["label"],
            "days_between": days,
            "from_area_m2": prev["area_m2"], "to_area_m2": curr["area_m2"],
            "drop_fraction": round(drop, 4),
            "drop_pct": round(100.0 * drop, 2),
            "from_open_water_fraction": prev["open_water_fraction"],
            "to_open_water_fraction": later_open,
            "spans_known_event": bool(curr["is_post_event"]),
            "recovery": recovery,
            "n_usable_follow_ups": follow_ups,
            # Three states, not two. "We could not tell" is a distinct and
            # honest answer, and collapsing it into either yes or no is how a
            # detector ends up reporting its own blind spots as findings.
            "status": ("confirmed" if confirmed_persistent and not reasons
                       else "unconfirmed_no_follow_up" if unconfirmed
                       else "suppressed"),
            "flagged": bool(confirmed_persistent and not reasons),
            "suppressed_reasons": reasons + (
                ["no usable observation within the recovery window, so a drained "
                 "lake cannot be distinguished from a frozen one; reported as a "
                 "candidate rather than a burst"] if unconfirmed else []),
            "thresholds_used": {"drop_fraction": frac, "max_days": max_days,
                                "min_open_water_fraction": min_open,
                                "recovery_fraction": recovery_frac},
        })
    return events


def analyse(lake: dict, lake_result: dict, cfg) -> dict:
    points = usable_points(lake_result, cfg)
    trend = trend_features(points, cfg)
    drops = detect_drops(points, cfg)
    flagged = [d for d in drops if d["flagged"]]
    return {
        "lake_id": lake["id"],
        "name": lake["name"],
        "class": lake["class"],
        "label_burst": lake["label_burst"],
        "trend": trend,
        "drops_detected": flagged,
        "drops_unconfirmed": [d for d in drops
                              if d["status"] == "unconfirmed_no_follow_up"],
        "drops_suppressed": [d for d in drops if d["status"] == "suppressed"],
        "burst_detected": bool(flagged),
        "config": {
            "sudden_drop_fraction": cfg.require("trajectory.sudden_drop_fraction"),
            "min_open_water_fraction": cfg.require("trajectory.min_open_water_fraction"),
            "min_series_length": cfg.require("trajectory.min_series_length"),
        },
        "observations": points,
    }
