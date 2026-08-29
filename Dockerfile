# Stage 17 reproduction image. Written at Stage 0 so `make docker-build` is
# never a broken target; formally built and gated in Stage 17.
#
# Pinned to the same CPython minor as the development machine (3.13) so the
# lockfile resolves identically in both places.
FROM python:3.13-slim-bookworm

# GDAL/PROJ come from the rasterio/pyproj manylinux wheels, so only build-time
# essentials are needed here. Kept minimal to keep the image auditable.
RUN apt-get update && apt-get install -y --no-install-recommends \
        make \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONHASHSEED=0 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

WORKDIR /app

# Dependencies first so the (slow) wheel install layer caches across code edits.
COPY requirements.txt requirements-lock.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

# Pinned data is COPY'd, not fetched: the image must reproduce with
# `docker run --network none`.
COPY . .

CMD ["make", "reproduce"]
