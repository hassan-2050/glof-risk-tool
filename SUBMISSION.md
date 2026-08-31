# Submission — GLOF Risk Tool for Nepal

**Frontier Engineering Challenge 2026 · micro1**

A glacial lake outburst flood (GLOF) screening prototype: it ranks which
Himalayan glacial lakes are most dangerous, shows what lies downstream if one
releases, and drafts the situation report — from free satellite data, offline,
on any laptop, with no API key.

**Not an operational warning system.** Decision support *for* Nepal's DHM,
NDRRMA and ICIMOD, who own the data and the mandate.

---

## Start here

| you have | open |
|---|---|
| 5 minutes | the video, then `outputs/results.html` |
| 15 minutes | `README.md`, then `outputs/tools/map.html` — drag both sliders |
| you want to run it | `make reproduce` (Windows: `./make.ps1 reproduce`) — 5 min, offline, no key |

Nothing needs a server or a build step. `results.html`, `map.html`,
`agents.html` and `changelog.html` all open by double-clicking them.

---

## What existed before the challenge, and what was built during it

**Everything in this repository was written during the challenge window.**
First commit 29 Aug 2026 09:28, last 31 Aug 2026; nothing was carried in from
prior work, and there is no pre-existing codebase behind it.

What was *not* built here, and is used as an input or a dependency:

- **Public data** — Sentinel-2 L2A scenes (Copernicus), Copernicus GLO-30 DEM,
  WorldPop 2020 constrained, OpenStreetMap (ODbL). All committed under
  `data/pinned/` and used within their licences.
- **Published science, used as fixed references rather than re-derived** —
  the 0.1 km² screening threshold (Rounce et al. 2017), the reach-angle stop
  rule (Huggel et al. 2003), volume–area error bounds (Cook & Quincey 2015),
  the priority-flood depression fill (Barnes et al. 2014), ICIMOD PDGL
  rankings.
- **Standard libraries** — rasterio, numpy, scipy, shapely, pyproj, Pillow.
- **A language model** for Stages 11 and 15, with every response committed to
  `data/pinned/llm_cache/` so the pipeline reproduces without a key.

## The primary metric

Success for the intended user is **catching a lake that is about to burst,
without being told which one to look at**. That is the recall row.

| metric, same 14 lakes and same cutoffs | baseline | this solution | change |
|---|---|---|---|
| **burst recall** (primary) | 0.000 | **0.333** | +0.333 |
| precision | 0.000 | 0.500 | +0.500 |
| F1 | 0.000 | **0.400** | +0.400 |
| Thame rank, threshold-free | never assessed | **1 of 13** | — |
| cost per full run | $0 | **$0** | — |
| wall-clock per full run | — | **4 m 52 s** | — |

And for the reporting task, 10 scenarios against a single-prompt baseline:

| metric | baseline | this solution | change |
|---|---|---|---|
| **contradiction recall** (primary) | 0.000 | **0.950** | +0.950 |
| hallucination rate | 0.344 | **0.091** | −0.253 |
| numeric accuracy | 0.656 | **0.909** | +0.253 |
| citation F1 | 0.000 | **0.535** | +0.535 |

**Not measured, and not claimed:** human time per task. Comparing against a
human analyst would need a timed human baseline, which was not run — so no
time-saving figure is asserted anywhere in this submission.

## The challenging case, and what it revealed

**South Lhonak** is the case that fails, and it is the most informative one
here.

It burst on 3 October 2023 and destroyed Chungthang 60 km downstream. The
screen does not catch it, and the corridor does not reach the town: routing
stops at 31 km. The diagnosis is not a tuning problem — **its moraine is
unbreached in the DEM**, so there is no topographic path out of the basin for
a flow router to follow. A 30 m DEM acquired before the breach cannot contain
the channel the flood actually cut.

What it revealed, and what changed because of it: reach-angle routing on a
pre-event DEM is bounded by the terrain it was given, and no amount of
parameter adjustment fixes a missing outlet. It is reported as a miss rather
than tuned away, and it is why the runout figures are published as a
**bracket** between two regimes instead of a prediction. South Lhonak is also
one of only two lakes the calibration policy permits tuning on
(`data/labels/cutoffs.json`), which makes leaving it failing a deliberate
choice rather than an oversight.

A second hard case runs the other way: **Chamoli** is a negative control the
system must *refuse*. It finds 300 m² of scattered meltwater, fires zero
proxies, and declines to call it a lake burst — in English, in Nepali, and in
the machine-readable CAP export.

---

## Where each judging criterion is answered

### Problem & user value — 15%

The user is a hazard officer at DHM/NDRRMA deciding **where to send a survey
team**, because nobody can instrument every glacial lake in Nepal.

The bottleneck is that the standard first filter — area-growth screening —
fails in two documented, opposite ways. Thyanbo Tsho above Thame burst on
16 Aug 2024 measuring **0.0384 km²**, below the 0.1 km² screening threshold of
Rounce et al. (2017), so it was never assessed at all. And Chamoli (2021)
killed 200+ but was a rock-and-ice avalanche, **not** a lake outburst — a
system that cannot say so is not measuring what it claims to.

- `README.md` → "The claim"
- `docs/DEMO-STORY.md` → the narrative, including the valley hit again in Aug 2026

### Agent solution & engineering — 30%

**`outputs/tools/agents.html`** is the one-page answer: eight agents, colour-
separated by whether their output is deterministic or model-generated, each
carrying the design choice it exists to make.

The argument is *where agency helps and where it deliberately does not*:

1. **Numeric extraction is rule-based, not model-based** — the whole value of
   the contradiction table is that you can check it; an LLM would make the one
   auditable part nondeterministic.
2. **Two checks that fail differently** — a rule-based verifier ("is this
   figure in the span it cites?", so it cannot hallucinate a verdict) and an
   adversarial critic attacking what the verifier cannot see.
3. **The LLM critic is advisory and cannot clear a draft** — a model allowed to
   approve its own output is a rubber stamp with extra steps.
4. **Refusal is a first-class output** — four sources say the Rasuwa flood hit
   4, 5, 8 or 11 hydropower projects; it reports the spread and says who claims
   what, including *intra-document* contradictions.
5. **The trajectory log is derived from artefacts, not narrated** — it
   structurally cannot claim what the outputs do not show.

- `README.md` → "How the solution uses agents, and why each choice"
- `src/reporter/` → the agents; the rationale is in each module's docstring
- `outputs/agent_trajectories.json` → 52 recorded steps across 4 events

### End-to-end quality — 20%

A complete, self-contained run produces artefacts a hazard officer could act
on: a ranked lake list, a downstream triage statement per lake, bilingual
sitreps behind a human approval gate, and CAP XML / HXL CSV exports.

- `outputs/tools/map.html` — measured lake outlines on a hillshade, a **draggable
  alarm threshold** that re-screens all 14 lakes live, the 100 km downstream
  corridors, and a **scenario dial**: *if the flow runs R km, who is in the way?*
- `outputs/tools/scenarios.md` — the triage statement per lake
- `python -m src.cli approve --list` — the approval ledger

### Measured improvement — 15%

Two baseline-vs-advanced comparisons, same cases, same cutoffs:

| | baseline | advanced |
|---|---|---|
| **watcher** — recall / precision / F1 | 0.0 / 0.0 / **0.0** | 0.333 / 0.5 / **0.400** |
| **reporter** — contradiction recall | 0.000 | **0.950** |
| **reporter** — hallucination rate | 0.344 | **0.091** |
| **reporter** — numeric accuracy | 0.656 | **0.909** |
| **reporter** — citation F1 | 0.000 | **0.535** |

Threshold-free version of the headline: **Thame ranks 1 of 13** on the
continuous source-to-lake volume ratio — this does not depend on the alarm
threshold, which was set after seeing every score and is therefore not a blind
holdout.

- `CHANGELOG_improvements.md` / `outputs/tools/changelog.html` — every iteration
  as hypothesis → change → measured result → evidence, **generated from the run**
- `outputs/results.html`, `docs/RESULTS.md`

**The change that contributed most:** routing moved from a 7 km box to a 100 km
river domain (D19). Corridors went from a 3.5 km cap to 31–127 km, which is
what made scoring against real destroyed villages possible at all — the
corridors now name **3 of 5** documented impact sites, all three within 2× of
the observed distance (Thame 7.6 km vs 10, Rasuwagadhi 35.1 vs 36, Reni 22.3
vs 13).

**An experiment removed:** a priority-flood spanning-tree router that gave
every lake the same ~70 km straight line, because a traversal tree meanders
around a catchment instead of running down a river. Replaced with steepest
descent (`src/watcher/routing_long.py`).

### Reproducibility — 15%

```bash
make reproduce            # Windows: ./make.ps1 reproduce
```

**~5 minutes** (measured 4 m 52 s), **$0**, **no API key**, **no network** —
access is blocked in-process, so a stage that grew a hidden download would
crash rather than quietly succeed. Language-model responses replay from a
committed cache; a miss is a hard error, never a silent live call.

- `make verify-determinism` — two cold runs, every artefact hash diffed
- `outputs/run_manifest.json` — sha256 of every artefact
- `Dockerfile` — pinned `python:3.13-slim` + `requirements-lock.txt`
- Stage 17 re-reads `README.md` and **fails the run** if a headline figure drifts

### Hot take — 5%

**An agent's most dangerous output is a zero, because a zero never looks like a
failure.** Under rate limiting, Overpass returned HTTP 200 with an empty
element list — status success, schema valid — and the exposure agent cached it
and reported *no assets downstream* for 126 km of populated Himalayan valley.

The same shape appeared three more times: raster nodata summed as "nobody lives
here", an unqueried lake rendering identically to an empty one, a corridor
truncated at a window edge reading as "the flood stops here".

The lesson: **a tool contract needs three states, not two** — `ok / empty /
failed` — and the agent must never treat the middle as the first. Full argument
in `README.md` → "Hot take".

---

## Agent trajectories

Two different kinds, and they are not the same thing — `submission/agent_traces/`
holds both, with a README explaining the distinction:

- **the product's own agents** — `outputs/agent_trajectories.json`, a pipeline
  artefact regenerated by Stage 17 on every run
- **the coding agent that built the repo** — Claude Code; 3,000+ turns and
  1,100+ tool calls, exported redacted and self-verified, with four
  representative episodes chosen for what they show (three of the four are the
  agent being wrong and finding out from a tool)

Regenerate with `python tools/export_agent_traces.py`.

---

## What this deliberately refuses to say

It cannot predict **when**. There is no forecast, no real-time path, and it
must not be used to alert the public. It measures surface geometry, not
moraine-dam strength, ice-core presence or bathymetry. Corridors are indicative
screening corridors from a 90 m DEM — position, not inundation: no depth, no
discharge, no hydraulics. Volume estimates carry 50 to >400% error and are
emitted as bands.

And the sharpest limit is inside the headline result itself: restricted to
genuinely pre-event data, the growth baseline **cannot even compute a growth
rate** for Thame — one usable annual observation, the other six lost to monsoon
cloud. Only **1 of 16** pre-event scenes across the four events clears the QA
gate. That is the strongest argument in this repository for Sentinel-1 SAR
fusion, and it is documented rather than hidden.

`docs/LIMITS.md` and `docs/ETHICS.md` carry the full list, generated from the
run on every reproduce.
