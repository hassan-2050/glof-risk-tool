# GLOF Risk Tool for Nepal

**Research prototype — not an operational warning system.** Decision-support
*for* DHM, NDRRMA and ICIMOD, who own the data and the mandate.

---

## The claim

Area-growth screening — the industry-standard first filter for glacial-lake
outburst flood (GLOF) hazard — fails in two documented, opposite ways:

- **False negative.** Thyanbo Tsho above Thame burst on 16 Aug 2024. It was
  ~0.05 km², *below* the 0.1 km² screening threshold of Rounce et al. (2017),
  and stable in area from 2017–2023. It was triggered by a rock/ice avalanche.
  A two-date growth screen would have missed it entirely.
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

## Status

| Stage | | Stage | |
|---|---|---|---|
| 00 Determinism scaffolding | **done** | 09 Numeric reconciliation | pending |
| 01 Pinned dataset + labels | pending | 10 Drafting agent | pending |
| 02 Lake delineation | pending | 11 Critic + NLI verification | pending |
| 03 Trajectory + burst detect | pending | 12 Provenance ledger | pending |
| 04 Proxy engine | pending | 13 CAP XML + HXL CSV | pending |
| 05 Exposure overlay | pending | 14 Reporter eval | pending |
| 06 Flow routing | pending | 15 Nepali translation QA | pending |
| 07 Watcher eval | pending | 16 Negative control | pending |
| 08 Retriever agent | pending | 17–18 Packaging + docs | pending |

`python -m src.cli list-stages` prints the live version of this table.

## Quick start

```bash
python -m pip install -r requirements.txt
make reproduce            # Windows: ./make.ps1 reproduce
```

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
Full limits and ethics sections ship in Stage 18.
