"""Stage 0 pass criteria, as executable tests."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.common import determinism as det          # noqa: E402
from src.common.config import load_config          # noqa: E402
from src.common.io import dumps_json, manifest_for # noqa: E402


def test_frozen_clock_is_stable():
    cfg = load_config()
    iso = cfg.require("determinism.frozen_utc")
    assert det.frozen_now(iso) == det.frozen_now(iso)


def test_offline_guard_blocks_sockets():
    """The no-network claim must be enforced, not asserted."""
    import socket
    det.engage_offline_guard()
    try:
        with pytest.raises(det.NetworkAccessBlocked):
            socket.create_connection(("example.com", 80), timeout=1)
    finally:
        det.release_offline_guard()
    # ...and releasing must actually restore it, or Stage 1 fetch would break.
    assert socket.create_connection is det._REAL_CREATE_CONNECTION


def test_json_canonicalisation_is_order_independent():
    """Dict insertion order must not change output bytes."""
    a = {"z": 1, "a": {"q": 2, "b": 3}}
    b = {"a": {"b": 3, "q": 2}, "z": 1}
    assert dumps_json(a) == dumps_json(b)


def test_float_rounding_absorbs_last_ulp():
    """A 1-ULP difference from a reordered reduction must not change bytes."""
    assert dumps_json({"v": 0.1 + 0.2}) == dumps_json({"v": 0.3})


def test_negative_zero_collapses():
    assert dumps_json({"v": -0.0}) == dumps_json({"v": 0.0})


def test_every_threshold_lives_in_config():
    """Stage 3 criterion, enforced from Stage 0: no inline scientific constants.

    Guards the specific magic numbers a reviewer would challenge. If a stage
    hardcodes one, this fails and points at the file.
    """
    banned = {
        "2.2": "delineation.glacier_nir_swir1_ratio",
        "0.104": "proxies.volume_area.huggel_2002.coeff",
        "0.1217": "proxies.volume_area.cook_quincey_2015.coeff",
        "1.4129": "proxies.volume_area.cook_quincey_2015.exp",
    }
    offenders = []
    for path in (REPO / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for literal, key in banned.items():
            # allow the literal inside a comment or docstring line
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if literal in stripped and not stripped.startswith("#") \
                        and "config" not in stripped and '"' not in stripped:
                    offenders.append(f"{path.relative_to(REPO)}:{i} -> use cfg.require('{key}')")
    assert not offenders, "hardcoded thresholds found:\n" + "\n".join(offenders)


def test_config_thresholds_carry_citations():
    """Stage 4 criterion: every proxy states source paper + confidence tier."""
    cfg = load_config()
    tiers = {"published", "moderate", "derived"}
    for name in cfg.require("proxies"):
        if name == "volume_area":
            groups = [f"proxies.volume_area.{k}" for k in
                      ("huggel_2002", "cook_quincey_2015")]
        else:
            groups = [f"proxies.{name}"]
        for g in groups:
            c = cfg.cite(g)
            assert c["confidence_tier"] in tiers, f"{g}: bad tier {c}"
            assert "unsourced" not in c["source"], f"{g}: missing source paper"


@pytest.mark.slow
def test_reproduce_is_byte_identical_across_two_cold_runs():
    """The headline Stage 0 criterion. Two cold processes, identical bytes."""
    env = {"PYTHONHASHSEED": "0", "OMP_NUM_THREADS": "1",
           "PATH": __import__("os").environ.get("PATH", ""),
           "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    hashes = []
    for _ in range(2):
        r = subprocess.run([sys.executable, "-m", "src.cli", "reproduce"],
                           cwd=REPO, env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        m = manifest_for(REPO / "outputs")
        m.pop("run_manifest.json", None)  # the manifest hashes the others
        hashes.append(m)
    assert hashes[0] == hashes[1]
