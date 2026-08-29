"""Determinism enforcement.

Stage 0 pass criteria demand that `reproduce` (a) runs with no network and
(b) produces byte-identical output across runs. Rather than asserting either,
this module makes both mechanically true and loudly fails when they are not.

Three sources of run-to-run drift are closed here:
  1. RNG state          -> seed_everything()
  2. Wall clock         -> frozen_now(), and a ban on datetime.now()
  3. Thread scheduling  -> single-threaded BLAS (parallel float reductions
                           are not bit-reproducible)

Hash-order drift (PYTHONHASHSEED) cannot be fixed from inside a running
interpreter, so it is set by the Makefile / entrypoint and only *verified*
here.
"""
from __future__ import annotations

import os
import random
import socket
import sys
from datetime import datetime, timezone

_OFFLINE_ENGAGED = False
_REAL_SOCKET = socket.socket
_REAL_CREATE_CONNECTION = socket.create_connection


class NetworkAccessBlocked(RuntimeError):
    """Raised when reproduce-path code attempts a network call."""


def set_thread_limits(n: int = 1) -> None:
    """Pin BLAS/OpenMP thread counts.

    Must run before numpy is imported to take effect, which is why the CLI
    calls this first thing.
    """
    for var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        os.environ[var] = str(n)


def seed_everything(seed: int) -> None:
    """Seed every RNG we might touch.

    Deliberately does NOT touch PYTHONHASHSEED. That variable is read only at
    interpreter start, so writing it here would have no effect on this process
    while silently handing child processes a *different* hash seed than the
    parent - which is exactly the kind of split-brain nondeterminism this
    module exists to prevent. It is set by the Makefile and only verified here.
    """
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:  # numpy-free contexts (e.g. doc builds)
        pass


def verify_hash_seed(expected: int) -> None:
    """PYTHONHASHSEED must be set *before* interpreter start; we can only check.

    An unset value means str/bytes hashing is randomised, which can reorder
    set iteration and therefore output bytes.
    """
    actual = os.environ.get("PYTHONHASHSEED")
    if actual is None:
        raise RuntimeError(
            "PYTHONHASHSEED is not set. Byte-identical output cannot be "
            f"guaranteed. Run via `make reproduce` or export PYTHONHASHSEED={expected}."
        )
    if actual != str(expected):
        raise RuntimeError(
            f"PYTHONHASHSEED={actual!r} but config expects {expected!r}."
        )


def frozen_now(iso: str) -> datetime:
    """The only clock the reproduce path may read."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def engage_offline_guard() -> None:
    """Hard-block outbound sockets for the rest of the process.

    This is what turns "runs offline" from a claim into a proof: if any stage
    silently depends on a live download, reproduce crashes instead of quietly
    succeeding on a machine that happens to have network.
    """
    global _OFFLINE_ENGAGED

    def _blocked(*args, **kwargs):
        raise NetworkAccessBlocked(
            "Network access attempted on the reproduce path. All inputs must "
            "come from committed files under data/pinned/. If you are adding a "
            "download step, it belongs in `make fetch-data` (Stage 1), not here."
        )

    socket.socket = _blocked  # type: ignore[assignment]
    socket.create_connection = _blocked  # type: ignore[assignment]
    _OFFLINE_ENGAGED = True


def release_offline_guard() -> None:
    """Restore sockets. Used only by the Stage 1 data-fetch tooling and tests."""
    global _OFFLINE_ENGAGED
    socket.socket = _REAL_SOCKET  # type: ignore[assignment]
    socket.create_connection = _REAL_CREATE_CONNECTION  # type: ignore[assignment]
    _OFFLINE_ENGAGED = False


def offline_engaged() -> bool:
    return _OFFLINE_ENGAGED


def environment_fingerprint() -> dict:
    """Recorded into every run manifest so a mismatched reproduction is visible.

    Deliberately excludes hostname/username/paths - those differ between the
    author's machine and a judge's, and would break byte-identity for no
    scientific reason.
    """
    return {
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
        "thread_limit": os.environ.get("OMP_NUM_THREADS"),
    }
