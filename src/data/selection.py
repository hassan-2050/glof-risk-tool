"""Which scenes to pin, and why.

Scene choice is a scientific decision, not plumbing, so it lives in its own
module with the reasoning attached rather than buried in the downloader.

Three kinds of scene enter the pinned set:

  annual     one per year per lake, for the Stage 3 trajectory. Targeted at the
             post-monsoon window (mid-Sep to mid-Dec) because that is when
             Himalayan lakes are simultaneously cloud-free, unfrozen, and at
             stable level. The published Thyanbo series (Bisht et al. 2025)
             uses exactly this window - 12 Sep 2017, 10 Oct 2019, 14 Oct 2021,
             9 Oct 2023 - so our series is comparable to theirs by construction.

  event      tight brackets either side of each hindcast event, so Stage 3's
             burst detector sees the actual drop. The pre-event member is hard
             capped at the lake's cutoff date; the post-event member is tagged
             so Stage 7 cannot see it.

  qa_hard    at least one deliberately cloud- or shadow-affected scene. Stage 2
             must FLAG this rather than silently mis-measure it, and we cannot
             demonstrate that with a set curated to be clean. Choosing the
             worst scene on purpose is the only honest way to test the QA path.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Literal

SceneRole = Literal["annual", "event_pre", "event_post", "qa_hard"]

# Post-monsoon window. Before mid-Sep the monsoon still clouds the range;
# after mid-Dec seasonal ice starts biasing the delineation low.
# Measured correction. The original window ran to 15 December, and the
# resulting Dec-2023 Thyanbo scene delineated 144,800 m2 against a published
# ~36,827 m2 for that year - a 4x overestimate, because at 4,900 m the lake is
# frozen and the basin is snow-covered by December, and fresh snow is a
# textbook NDWI false positive. Ending 15 November keeps the post-monsoon
# clarity while staying ahead of reliable freeze-up. The published Thyanbo
# series (12 Sep, 10 Oct, 14 Oct, 9 Oct) sits entirely inside this window.
ANNUAL_WINDOW = ((9, 15), (11, 15))
ANNUAL_YEARS = tuple(range(2017, 2026))

# Sentinel-2 L2A coverage is patchy before 2018 outside Europe, so early years
# are allowed to be missing rather than forcing a bad scene into the series.
YEARS_ALLOWED_MISSING = (2017,)

# Cloud ceilings. The annual series wants clean scenes; the event brackets take
# what the calendar gives, because a GLOF does not wait for a clear sky.
MAX_CLOUD_ANNUAL = 35.0
MAX_CLOUD_EVENT = 90.0

# A scene must be at least this cloudy to serve as the deliberate QA test case.
MIN_CLOUD_QA_HARD = 60.0

# Days either side of an event to search for the bracketing pair.
EVENT_PRE_DAYS = 60
EVENT_POST_DAYS = 75


# How many candidates to pin per request.
#
# Annual scenes take 1: the post-monsoon window reliably yields a genuinely
# clear scene (0-15% tile cloud in practice), so there is nothing to choose
# between.
#
# Event brackets take several, because tile-level eo:cloud_cover is a bad
# proxy at this scale and we measured how bad: EVERY Sentinel-2 scene over the
# Thame window between 17 Jun and 15 Aug 2024 reports 80-99% cloud, including
# the 30 Jul scene from which Bisht et al. (2025) successfully derived a lake
# area. The cloud sits over the 110 km tile, not necessarily over the 5 km lake
# window. Selecting on the tile figure would have discarded the single most
# important observation in the project.
#
# So the fetcher pins the candidates and Stage 2 ranks them on window-level
# cloud computed from SCL, per its own pass criteria. Scene choice becomes a
# measured decision on committed data rather than a metadata guess.
N_CANDIDATES_EVENT = 4
N_CANDIDATES_ANNUAL = 1


@dataclasses.dataclass(frozen=True)
class SceneRequest:
    lake_id: str
    role: SceneRole
    start: dt.date
    end: dt.date
    max_cloud: float
    label: str
    reason: str
    # Hard leakage guard: no scene later than this may be tagged pre-event.
    cutoff: dt.date | None = None
    n_candidates: int = 1


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def annual_requests(lake_id: str) -> list[SceneRequest]:
    out = []
    for year in ANNUAL_YEARS:
        (sm, sd), (em, ed) = ANNUAL_WINDOW
        out.append(SceneRequest(
            lake_id=lake_id, role="annual",
            start=dt.date(year, sm, sd), end=dt.date(year, em, ed),
            max_cloud=MAX_CLOUD_ANNUAL, label=f"annual_{year}",
            reason=("post-monsoon window: cloud-free, unfrozen, stable level; "
                    "matches the window used by the published Thyanbo series"),
        ))
    return out


def event_requests(lake_id: str, event_date: str, cutoff: str) -> list[SceneRequest]:
    ev, cut = _d(event_date), _d(cutoff)
    return [
        SceneRequest(
            lake_id=lake_id, role="event_pre",
            start=ev - dt.timedelta(days=EVENT_PRE_DAYS), end=cut,
            max_cloud=MAX_CLOUD_EVENT, label="event_pre", cutoff=cut,
            n_candidates=N_CANDIDATES_EVENT,
            reason=(f"most recent acquisitions on or before the {cutoff} cutoff; "
                    "these are the only views the screening decision may use. "
                    "Several are pinned because tile-level cloud cover does not "
                    "predict window-level usability - Stage 2 ranks them on SCL."),
        ),
        SceneRequest(
            lake_id=lake_id, role="event_post",
            start=ev + dt.timedelta(days=1),
            end=ev + dt.timedelta(days=EVENT_POST_DAYS),
            max_cloud=MAX_CLOUD_EVENT, label="event_post",
            n_candidates=N_CANDIDATES_EVENT,
            reason=("earliest acquisitions after the event, for Stage 3 burst "
                    "detection; tagged post_event and hidden from Stage 7"),
        ),
    ]


def qa_hard_request(lake_id: str, year: int = 2023) -> SceneRequest:
    """Deliberately pick a bad scene during the monsoon.

    Mid-monsoon over the Khumbu is close to a guaranteed cloud/shadow case,
    which is what we want: a QA flag that only ever sees clean data proves
    nothing.
    """
    return SceneRequest(
        lake_id=lake_id, role="qa_hard",
        start=dt.date(year, 6, 15), end=dt.date(year, 8, 31),
        max_cloud=100.0, label=f"qa_hard_{year}",
        reason=("deliberately cloud/shadow-affected monsoon scene; Stage 2 must "
                "flag it rather than silently mis-measure the lake"),
    )


def requests_for_lake(lake: dict, cutoffs: dict) -> list[SceneRequest]:
    lid = lake["id"]
    reqs = annual_requests(lid)
    per = cutoffs.get("per_lake", {}).get(lid, {})
    if lake.get("event_date") and per.get("cutoff"):
        reqs += event_requests(lid, lake["event_date"], per["cutoff"])
    return reqs
