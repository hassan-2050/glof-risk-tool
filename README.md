# GLOF Risk Tool for Nepal

**Research prototype — not an operational warning system.** Decision-support
*for* DHM, NDRRMA and ICIMOD, who own the data and the mandate.

---

## The claim

Area-growth screening — the industry-standard first filter for glacial-lake
outburst flood (GLOF) hazard — fails in two documented, opposite ways:

- **False negative.** Thyanbo Tsho above Thame burst on 16 Aug 2024. On our last
  pre-event scene it measured 0.0198 km², *below* the 0.1 km² screening
  threshold of Rounce et al. (2017), and it was stable in area from 2017–2023.
  It was triggered by a rock/ice avalanche. A two-date growth screen would have
  missed it entirely.
  **Read this qualification with it:** the event was a *cascade* of two lakes,
  and the one that failed first — Upper Ngole Cho, 0.11 km² — was marginally
  *above* the screen and had grown sixfold since 2010. We measure the lower
  lake. The screening failure is still the finding of the researchers who
  studied the event, who name minimum-size thresholds as the reason both lakes
  were missed, but our single-lake framing understates the event. DECISIONS D15.
- **Misattribution.** Chamoli (7 Feb 2021) killed 200+ but was a rock-and-ice
  avalanche, **not** a lake outburst. A hazard system that cannot say so is not
  measuring what it claims to measure.

This repository does three things about that:

1. a **proxy-augmented watcher** that reasons about triggers and dam geometry,
   not trend lines;
2. a **multi-agent reporter** whose most valuable output is often a refusal —
   surfacing that four sources disagree on how many hydropower projects Rasuwa
   destroyed, rather than fluently averaging them away;
3. a **fair baseline-vs-advanced evaluation** proving both, on the same cases,
   with pre-event cutoffs and no hindsight leakage.

## Status — all 19 stages complete

`python -m src.cli list-stages` prints the live table.

## Headline results

The authoritative copies live in [`docs/RESULTS.md`](docs/RESULTS.md) and
[`CHANGELOG_improvements.md`](CHANGELOG_improvements.md), both written by
Stage 18 *from* the pipeline so they cannot drift from it. The figures repeated
below are typed, so Stage 17 re-reads this file and **fails the run** if any of
them no longer matches what the pipeline produced.

**The claim, tested.** Growth-only screening vs. proxy-augmented, same 14 lakes,
same pre-event data, cutoffs enforced on every run:

| | growth-only | proxy-augmented |
|---|---|---|
| recall | 0.0 | **0.3333** |
| precision | 0.0 | 0.5 |
| F1 | 0.0 | **0.4** |

Growth-only catches nothing over this window. That is a weaker baseline than an
earlier version of this table reported, and the honest reading is a narrow one:
Sentinel-2 L2A only reaches back to 2017, and South Lhonak *is* growth-catchable
over 1962–2023. The result is a statement about an eight-year baseline, not
about area-growth screening for all time. See DECISIONS D13.

Thame appears in the growth-only **false negatives** and the proxy-augmented
**true positives**. Its area on the last pre-event scene is 0.0198 km² — below
the 0.1 km² Rounce screen, so a growth-only pipeline never assesses it at all.

Threshold-free version of the same claim: **Thame ranks 1 of 13** on the
continuous source-to-lake volume ratio. This matters because that alarm
threshold was set after seeing all thirteen values and is therefore *not* a
blind holdout — the rank statement does not depend on it. (Thirteen, not
fourteen: Chamoli impounds no water, so it has no ratio to rank.) Spearman
against the Rounce et al. (2017) expert classes: **0.378**.

**Reporter, 10 scenarios (4 real + 6 perturbed):**

| metric | single-prompt baseline | multi-agent |
|---|---|---|
| contradiction recall | 0.000 | **0.950** |
| hallucination rate | 0.344 | **0.091** |
| numeric accuracy | 0.656 | **0.909** |
| citation F1 | 0.000 | **0.535** |

Contradiction-detection F1 against the hand-labelled key: **0.857**. The
negative control holds end to end — watcher, sitrep in both languages, and the
CAP export.

## Why this is current, not historical *(written 31 Aug 2026)*

Five days before this submission, a rock-ice avalanche came down
Langtang-Lirung into the **Lhende Khola** — hundreds dead, attribution
initially wrong in both directions. That valley is in this evaluation set:
the **July 2025 Pyurepu GLOF ran the same river**, and our routed corridor
down it is validated to sub-kilometre on the bridge that flood destroyed
(35.1 km against a published 36 km). The corridor's asset list — 21
settlements, 4 hydropower sites, ~16,000 people within 500 m of the channel —
is a *standing* statement of what is in the way of the next event in that
valley, not a reconstruction of the last one.

Stated with equal clarity: this tool **screens lakes and would have been
silent on last week's slope** — the initiating hazard held no lake, and the
event is four days old as we write, so every figure about it is provisional.
What the event leaves behind, a landslide-dammed lake in the same channel, is
precisely the class of standing hazard this pipeline exists to watch, and it
is the first candidate for the lake set the day post-event imagery clears the
QA gate. The monsoon-blindness limit documented below is not weakened by that
event; it is demonstrated by it.

## Baseline and advanced, stated plainly

Every claim of improvement here is a same-cases, same-cutoffs comparison
against a genuine baseline, twice over:

| | baseline | advanced | measured on |
|---|---|---|---|
| **watcher** | area-growth screening (the industry-standard first filter) | proxy-augmented screen | 14 lakes, pre-event cutoffs |
| **reporter** | single-prompt summariser | multi-agent with reconciliation, critic, provenance | 10 scenarios, hand-labelled key |

The advanced watcher is a strict superset of the baseline — every baseline
flag is inherited — so its recall can never win by simply being different.
Both comparisons run from the same committed data with the same enforced
cutoffs, and both are one command (`make watcher-eval`, `make reporter-eval`).

## Quick start

```bash
python -m pip install -r requirements.txt
make reproduce            # Windows: ./make.ps1 reproduce
```

**Runtime and cost.** A full `reproduce` takes **about 5 minutes** on an
ordinary laptop (measured: 4 m 52 s, Windows 11, Python 3.13) and costs
**$0** — no API key, no network, no cloud. `make verify-determinism` is two
cold reproduces, ~10 minutes. The downstream chain (`make scenarios`) is
~12 minutes, dominated by the priority-flood pit fill on fourteen 100 km
DEMs; `make map` is ~2 minutes. Docker adds a one-time image build.

`reproduce` runs the full pipeline from committed data under `data/pinned/`
with **network access blocked in-process** — not merely unused. If any stage
ever grows a hidden download, the run crashes rather than quietly succeeding on
a machine that happens to be online.

| target | what it does |
|---|---|
| `make reproduce` | full watcher + reporter run, offline, from committed data |
| `make verify-determinism` | runs `reproduce` twice in cold processes, diffs every artefact hash |
| `make watcher-eval` | Stage 7 only — growth-only baseline vs. proxy-augmented |
| `make reporter-eval` | Stage 14 only — single-prompt baseline vs. multi-agent |
| `make test` | unit tests, including the determinism gate |
| `make fetch-data` | **Stage 1 only.** Needs network. Deliberately *not* part of `reproduce`. |

## Looking at the results

`outputs/results.html` is generated by Stage 18 from the same artefacts as the
docs — open it from disk, no server and no build step. It carries the confusion
matrix, the delineation validation, the baseline-vs-advanced comparison and the
contradiction table, with each caveat placed beside the number it qualifies.

`outputs/tools/map.html` is the interactive view — the lake outlines the
watcher actually measured, drawn on a hillshade of the DEM, with a year-by-year
time scrubber, the routed flood corridors, and a **draggable alarm threshold**
that re-screens all fourteen lakes and rebuilds the confusion matrix as it moves.
That last control is deliberate: the 5.0 alarm level was chosen after seeing
every score, and the fastest way to show what does and does not depend on it is
to let a reviewer move it. Build it with `make map` (Windows: `./make.ps1 map`).

The map also carries the downstream story: a **Downstream 100 km** layer
draws the routed channel over a wide hillshade with every named place the
exposure tool found, rings each documented flood impact at its predicted
distance, and a **scenario dial** — *"if the flow runs R km"* — that
conditions the corridor, the asset counts and the WorldPop sum on one
draggable distance, with the observed reach of each real event marked on the
slider. A capacity line projects the release band 12 months forward on the
Theil–Sen slope Stage 3 already fits — a **capacity forecast, never a hazard
forecast**: Thame was stable in area and burst anyway, so the trend only sets
how much water is waiting when a trigger arrives.

It has **no live feed and no tile server** — every scene is a committed
2017–2025 acquisition, the relief is rendered from the pinned DEM, and the page
opens from disk with the network off. `make check-map` re-verifies it against
the pipeline artefacts — 32 checks, including that its confusion matrix
reproduces Stage 7 exactly at the published threshold and that the scenario
dial's counters equal the exposure artefact's counts.

## Downstream scenarios — where the water goes, and past what

```bash
make scenarios          # route far, count what is downstream, score it
```

The 90 m downstream DEMs and the OpenStreetMap corridor extracts are
**committed under `data/pinned/`**, so `make scenarios` runs offline from a
fresh clone — verified by running the chain with a poisoned proxy.
`make fetch-downstream` exists to re-fetch the DEMs from source and is only
needed to extend the lake set.

`outputs/tools/scenarios.md` is the triage statement per lake — *if this lake
releases this volume band, flow reaches between X and Y km down this river, past
these settlements in this order*. For Thame that reads: 0.5–126.5 km down the
Dudh Koshi, past Thyangbo (2.3 km), **Thame (7.6 km)**, Samde, Thamo.

**It is scored against the villages the floods actually destroyed**, not just
against runout distance — a corridor down the wrong valley can travel the right
distance. Of five documented impact sites, the corridors name **three, all
three at a distance within 2× of the observed one**: Thame at 7.6 km against
10 km, Rasuwagadhi at 35.1 km against 36 km, and Reni at 22.3 km against
13 km. South Lhonak still fails; its
moraine is unbreached in the DEM, so there is no topographic path out of the
basin (DECISIONS D18–D20).

Every figure is a **range** and the reach is a **bracket** between the debris
and clear-water regimes — often two orders of magnitude wide, with the observed
reach inside it on 2 of 4 events. Assets are listed by position within 500 m of
a routed channel: no depth, no discharge, no hydraulics, and nothing about
*when*.

[`docs/GLOF-tool-overview.pdf`](docs/GLOF-tool-overview.pdf) is the two-page
plain-language version for a non-specialist reader — what a GLOF is, why size
screening missed Thame, what the tool does and what it cannot do. Regenerate it
after a run with `pip install reportlab && python tools/make_overview_pdf.py`;
like the docs, every figure in it is read from `outputs/`, not typed.

## Approving a sitrep

The Stage 12 gate is a real checkpoint, not a config value:

```bash
python -m src.cli approve --list          # decision status per draft
python -m src.cli approve                 # decide everything outstanding
python -m src.cli approve --draft thame_2024_en
```

It shows the contested figures, the verifier's unresolved claims and the
critic's findings, then requires a typed name and decision — a blank line is
refused. Decisions persist to `data/approvals/decisions.jsonl`, which
`reproduce` **reads but never writes**: Stage 12 deletes and rebuilds the
ledger every run for byte-identity, so a decision stored there would be
destroyed silently. Drafts with no recorded decision are labelled `SIMULATED`
in the ledger rather than passing quietly.

## Reproducing in a container

```bash
docker build -t glof-risk-tool:repro .
docker run --rm glof-risk-tool:repro          # runs `make reproduce`
```

The image pins `python:3.13-slim` and installs `requirements-lock.txt` (the
fully-resolved lock, not the loose direct requirements — a float differing in
its last bit between GDAL builds changes output bytes). `PYTHONHASHSEED` and
single-threaded BLAS are set before the interpreter starts, because the hash
seed is read only at startup and cannot be fixed from inside a running process.

**No API key is needed.** Stages 11 and 15 use a language model, and every
response is recorded once into `data/pinned/llm_cache/` and committed. On the
reproduce path the cache is the *only* source and a miss is a hard error, never
a silent live call — so a reviewer gets the numbers in this README rather than
whatever the model returns today.

To re-record the cache after changing a prompt or a draft:

```bash
GEMINI_API_KEY=... python -m src.data.record_llm_cache
```

## Layout

```
config/config.yaml     every seed and every scientific threshold, with its
                       source paper and confidence tier attached
src/watcher/           delineation, trajectory, proxies, exposure, routing
src/reporter/          retriever, reconciliation, drafter, critic, ledger
src/eval/              baseline-vs-advanced harnesses
data/pinned/           committed imagery, DEMs, document bundles (no downloads)
data/labels/           ground truth + per-event pre-event cutoff dates
outputs/               generated artefacts (hashed into run_manifest.json)
docs/DECISIONS.md      choices a reviewer might have made differently, and why
```

## Coding agents, disclosed

This repository was built with **Claude Code** (Anthropic, Opus-class models)
as the coding agent, across every stage: writing and revising the pipeline,
running it, reading the artefacts, and deciding the next change from what the
artefacts said. The iteration loop the changelog records — hypothesis, change,
measured result — is the agent's actual working loop, not a write-up
convention. Development-session trajectories accompany the submission package.

Two kinds of agent trace exist and should not be confused:

- **The product's own agents** — the multi-agent reporter (retriever,
  reconciler, drafter, critic, verifier). Their per-event trajectories are an
  artefact of every run: `outputs/agent_trajectories.json`, one step record
  per agent action, written by Stage 17.
- **The coding agent that built the repo** — session trajectories exported
  with the submission, showing instructions, tool calls, tool responses, and
  the human checkpoints between iterations.

No API key is needed to reproduce either: the pipeline's LLM calls replay from
`data/pinned/llm_cache/` (a miss is a hard error, never a silent live call).

## Reproducibility contract

- **Seeds** — `config/config.yaml → determinism`. `PYTHONHASHSEED` is set by the
  Makefile (it is read only at interpreter start) and *verified* in code.
- **Clock** — frozen at `determinism.frozen_utc`. Nothing on the reproduce path
  calls `datetime.now()`; a real timestamp would break byte-identity for no
  analytical gain.
- **Floats** — rounded to 6 dp before serialisation, absorbing last-ULP noise
  from reordered reductions without touching a meaningful digit.
- **Threads** — BLAS pinned to 1; parallel float reductions are not
  bit-reproducible.
- **Evidence** — `outputs/run_manifest.json` carries a sha256 of every artefact.

Every experiment is logged in
[`CHANGELOG_improvements.md`](CHANGELOG_improvements.md) with hypothesis,
change, metric before/after, and a link to the artefact that proves it —
including the experiments that did not work.

## Honest limits

This measures lake growth and **geometric proxies**. It does not measure
moraine-dam strength, ice-core presence, or bathymetry. Free 30 m DEMs are the
binding accuracy constraint for flow routing in narrow valleys, so inundation
outputs are **indicative corridors, not flood maps**. Empirical volume–area
estimates carry 50–>400% error (Cook & Quincey 2015) and are reported as bands.

Delineation validates on **6 of 8** lakes against published references. The two
that miss are Pyurepu 0.03× and South Lhonak 0.35×; the cause of each is
diagnosed rather than tuned away, in `docs/DECISIONS.md` D6, D12 and D14.
**Two of those six passes came from correcting our own reference data, not from
improving the measurement** — the pixels never changed (D14). Exposure counts are weak lower bounds —
corridors stop at the analysis-window edge while the Thame flood ran 80 km.
Optical monitoring is blindest during the monsoon, which is exactly when GLOFs
happen: **only 1 of the 16 pre-event scenes** across the four events clears the
cloud and snow QA gate.

`docs/LIMITS.md` carries these same figures derived from the run on every
reproduce; this paragraph is the hand-written echo of it.

Full detail: [`docs/LIMITS.md`](docs/LIMITS.md) and
[`docs/ETHICS.md`](docs/ETHICS.md), both generated from the run.

## Rules of the road, mapped

Where each engineering-conduct requirement is satisfied, so a reviewer does
not have to hunt:

| requirement | where |
|---|---|
| consequential actions gated by a human | Stage 12 approval CLI: typed name + decision, blank refused; undecided drafts labelled `SIMULATED` |
| qualified reviewer in the loop | same gate — nothing ships as "approved" without a recorded human decision |
| sandboxed / simulated consequences | no live alerts anywhere; CAP export is a file, the map has no feed, and `reproduce` runs with the network *blocked in-process* |
| data used within its licence | Sentinel-2 (Copernicus), OSM (ODbL, attributed), WorldPop (CC BY), GLO-30 (ESA); all public |
| no credentials in the repo | none needed — the LLM cache replays committed responses |
| every claim linked to evidence | figures in this README are re-read by Stage 17, which **fails the run** if any drifts from the artefacts; the changelog and docs are generated from `outputs/` |
| judges can reproduce the main result | `make reproduce` from a clean checkout, or the pinned Docker image |

## The main failure mode

**Optical monitoring goes blind exactly when the hazard is highest.** Three of
the four real events have *no usable pre-event scene at all* — monsoon cloud
kills 15 of 16 — so the last measurement before a burst is weeks to months
old, and nothing optical can shorten that. Everything else in this repository
degrades gracefully; this one is structural. It bounds the whole approach:
the tool can rank standing danger and lay out downstream consequence, but any
system promising *detection* of an imminent Himalayan GLOF from optical
imagery alone is promising something the atmosphere does not permit. The fix
is Sentinel-1 SAR fusion — radar sees through the monsoon — and that is the
first thing we would build next.

## Hot take

**The most dangerous number a hazard pipeline produces is a zero, because a
zero never looks broken.** A failed Overpass query rendered as "no assets
downstream". A nodata cell rendered as "nobody lives here". An unqueried lake
rendered as an empty one. A corridor that stops at a window edge rendered as
"the flood stops here". Every one of those wrong answers is *quiet* — it looks
exactly like a safe valley, and it fails in the direction that kills people.
Most engineering effort in this project did not go into the models; it went
into making absence-of-data **loud**: refusing to cache empty responses,
carrying "not measured" as a first-class value with its reason attached, and
printing the distance to the nearest person next to every zero. AI coding
agents make it cheap to generate pipelines that run end to end on the first
try; the frontier skill is noticing which of the numbers flowing through them
are silently wrong. A pipeline that says "I don't know" in the right places
is worth more than one that always has an answer.
