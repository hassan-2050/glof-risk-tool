# GLOF Risk Tool — reproducibility entry points.
#
# `make reproduce` is the contract: from a clean checkout, with no network,
# it must run the full watcher + reporter evaluation from committed data only.
#
# Windows note: GNU make is not installed by default. Use ./make.ps1 <target>,
# which forwards to the identical Python commands. The Makefile is what runs
# inside Docker (Stage 17) and is the canonical definition.

PY ?= python
# PYTHONHASHSEED must be set before interpreter start; it cannot be fixed from
# inside a running process, so every target exports it.
export PYTHONHASHSEED = 0
# Single-threaded BLAS: parallel float reductions are not bit-reproducible.
export OMP_NUM_THREADS = 1
export OPENBLAS_NUM_THREADS = 1
export MKL_NUM_THREADS = 1

.DEFAULT_GOAL := help
.PHONY: help setup reproduce watcher-eval reporter-eval verify-determinism \
        list-stages test fetch-data clean docker-build docker-reproduce

help:  ## show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}'

setup:  ## install pinned dependencies
	$(PY) -m pip install --require-hashes-off -r requirements.txt || \
	$(PY) -m pip install -r requirements.txt

reproduce:  ## FULL end-to-end run from committed data, network disabled
	$(PY) -m src.cli reproduce

watcher-eval:  ## Stage 7 only: growth-only baseline vs. proxy-augmented
	$(PY) -m src.cli stage 7

reporter-eval:  ## Stage 14 only: single-prompt baseline vs. multi-agent
	$(PY) -m src.cli stage 14

verify-determinism:  ## run reproduce twice, assert byte-identical artefacts
	$(PY) -m src.cli verify-determinism

list-stages:  ## show implemented vs. pending stages
	$(PY) -m src.cli list-stages

test:  ## unit tests
	$(PY) -m pytest -q tests

fetch-data:  ## Stage 1 ONLY. Requires network. Not part of `reproduce`.
	$(PY) -m src.data.fetch

# The three targets below are deliberately OUTSIDE `reproduce`. Each writes a
# large or non-deterministic artefact (JPEG hillshades, a PDF timestamp) that
# no stage reads, and folding them into the hashed set would trade a real
# guarantee for a convenience.
map:  ## rebuild outputs/map.html — interactive lake map, offline, no tiles
	$(PY) tools/build_map_data.py
	$(PY) tools/build_map_page.py
	$(PY) tools/build_agent_diagram.py
	$(PY) tools/build_changelog_page.py

check-map:  ## verify map.html against the pipeline artefacts (needs node)
	node tools/check_map_page.mjs

validate-routing:  ## compare predicted corridors with observed flood extents
	$(PY) tools/validate_routing.py

fetch-downstream:  ## Needs network. 100 km DEM per lake for long-range routing
	$(PY) -m src.data.fetch_downstream

scenarios:  ## route far, count what is downstream, write the triage list
	$(PY) tools/run_long_routing.py
	$(PY) tools/corridor_exposure.py
	$(PY) tools/build_scenarios.py
	$(PY) tools/validate_routing.py

overview-pdf:  ## rebuild docs/GLOF-tool-overview.pdf (needs reportlab)
	$(PY) tools/make_overview_pdf.py

clean:  ## remove generated outputs (never touches data/pinned)
	$(PY) -c "import shutil,pathlib; [shutil.rmtree(p,ignore_errors=True) for p in [pathlib.Path('outputs'),pathlib.Path('.determinism_check')]]; pathlib.Path('outputs').mkdir(exist_ok=True)"

docker-build:  ## build the pinned reproduction image (Stage 17)
	docker build -t glof-risk-tool:latest .

docker-reproduce:  ## run the full reproduction inside the container, no network
	docker run --rm --network none glof-risk-tool:latest make reproduce
