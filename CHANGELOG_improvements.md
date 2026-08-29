# Improvement Changelog

Every experiment gets an entry. The format is fixed so a reviewer can scan for
the thing that matters: **did the number move, and what is the evidence?**

    ## [stage N] short title — YYYY-MM-DD
    **Hypothesis:** what we expected and why
    **Change:** what was actually modified
    **Metric before → after:** the number, or "n/a (structural)" with a reason
    **Evidence:** path to the committed artefact that proves it

Entries are append-only. A failed experiment stays in the log — the negative
results are part of the honesty claim, not noise to be tidied away.

---

## [stage 0] Determinism scaffolding — 2026-08-29

**Hypothesis:** reproducibility retrofitted at the end is reproducibility that
does not exist. If the offline and byte-identity guarantees are only *asserted*
in a README, they will be quietly false by Stage 7 and nobody will notice until
a judge runs the container.

**Change:** built the skeleton with the guarantees mechanically enforced rather
than documented:
- `src/common/determinism.py` — `engage_offline_guard()` replaces
  `socket.socket` / `socket.create_connection` with a raising stub for the
  duration of `reproduce`. Any stage that grows a hidden download **crashes**
  instead of succeeding on a networked machine.
- `src/common/io.py` — all serialisation funnels through canonical writers:
  sorted keys, LF newlines, floats rounded to 6 dp before hashing. Closes the
  three drift sources (dict order, platform newlines, last-ULP float noise).
- Thread limits pinned to 1 before numpy import — parallel float reductions are
  not bit-reproducible.
- `config/config.yaml` — every scientific threshold, with its source paper and
  a confidence tier (`published` / `moderate` / `derived`) attached, so Stage 4
  can emit provenance without hardcoding citation strings.
- `python -m src.cli verify-determinism` runs `reproduce` in **two separate
  cold processes** and diffs the sha256 of every artefact. An in-process rerun
  would reuse warmed caches and could hide real nondeterminism.

**Metric before → after:** n/a (structural). Gate result: `verify-determinism`
**PASS** — 2/2 artefacts byte-identical across two cold runs; 8/8 tests pass.

**Bug found and fixed by this stage:** `seed_everything()` was writing
`PYTHONHASHSEED` at runtime. That has no effect on the running interpreter but
does hand child processes a *different* hash seed than the parent — a
split-brain nondeterminism that would have surfaced as an unexplained
`verify-determinism` failure in a much later stage. Now the variable is set by
the Makefile and only *verified* in code. This is the scaffolding paying for
itself before Stage 1.

**Deviations from the plan, and why:**
- `richdem` (plan: "`pysheds` or `richdem`") does not build on win-amd64 — no
  wheel, and its setup.py passes GCC-only flags to MSVC. Using `pysheds`.
- GNU `make` is absent on the development machine. The `Makefile` remains
  canonical (it is what runs inside the Stage 17 container); `make.ps1` is a
  thin shim forwarding identical commands so both paths execute the same code.

**Evidence:** `outputs/stage00_environment.json`, `outputs/run_manifest.json`,
`tests/test_determinism.py`
