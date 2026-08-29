# Reproduction image: clone, build, run, get the same numbers.
#
# Pinned to the exact interpreter and the fully-resolved dependency lock, not
# the loose direct requirements, because a float that differs in its last bit
# between GDAL builds changes output bytes and therefore breaks the Stage 0
# byte-identity claim.
FROM python:3.13-slim

# PYTHONHASHSEED must be set before the interpreter starts - it cannot be fixed
# from inside a running process, which is why determinism.py only verifies it.
# Single-threaded BLAS because parallel float reductions are not
# bit-reproducible.
ENV PYTHONHASHSEED=0 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8

# rasterio/pyproj ship manylinux wheels with GDAL and PROJ bundled, so no
# system GDAL is needed. build-essential covers any source-only wheel.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-lock.txt requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements-lock.txt

# Data before code: the pinned dataset changes rarely and the source often, so
# this ordering keeps the expensive layer cached across code edits.
COPY data/ ./data/
COPY config/ ./config/
COPY src/ ./src/
COPY tests/ ./tests/
COPY Makefile pyproject.toml ./
COPY docs/ ./docs/

# Proves the no-network claim rather than asserting it: the offline guard is
# engaged inside reproduce, so a stage that reaches for the network fails the
# build rather than silently succeeding on a machine that happens to be online.
CMD ["make", "reproduce"]
