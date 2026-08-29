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
# system GDAL is needed - but the bundled GDAL still links against base
# libraries that python:3.13-slim omits. libexpat1 is the one that bites:
# without it `import rasterio` fails with "libexpat.so.1: cannot open shared
# object file", and only at Stage 2, minutes into a run. Found by running the
# container; reading the Dockerfile could not have shown it.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential libexpat1 libgomp1 \
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
# The image carries its own build recipe. Stage 17 verifies the Dockerfile pins
# what it claims, and inside a container that check has nothing to read
# otherwise - it failed exactly there on the first real container run. Shipping
# it also means an auditor holding only the image can see how it was built.
COPY Dockerfile .dockerignore ./

# outputs/ is in .dockerignore (generated artefacts have no business in the
# build context), so the directory does not exist in the image and Stage 0's
# required-directory gate fails on the first run. Caught by actually running
# the container - inspecting the Dockerfile could not have shown it.
RUN mkdir -p outputs data/scratch

# Proves the no-network claim rather than asserting it: the offline guard is
# engaged inside reproduce, so a stage that reaches for the network fails the
# build rather than silently succeeding on a machine that happens to be online.
CMD ["make", "reproduce"]
