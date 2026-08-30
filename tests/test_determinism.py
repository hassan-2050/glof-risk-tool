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


def test_offline_guard_does_not_break_library_imports():
    """Regression: the guard must block CONNECTING, not socket construction.

    The first implementation replaced socket.socket with a function that
    raised. That broke every import which subclasses it - the stdlib ssl module
    does exactly that (`class SSLSocket(socket)`), so importing pyproj (which
    reaches ssl via urllib.request) died with "argument 'code' must be code,
    not str" from inside ssl.py. Stage 5 could not run at all, and the error
    pointed nowhere near the guard.
    """
    import importlib
    import socket

    det.engage_offline_guard()
    try:
        # These must all still import while the guard is engaged.
        for mod in ("ssl", "urllib.request", "http.client", "pyproj"):
            assert importlib.import_module(mod) is not None
        # Constructing a socket is fine; connecting is not.
        s = socket.socket()
        with pytest.raises(det.NetworkAccessBlocked):
            s.connect(("93.184.216.34", 80))
        s.close()
    finally:
        det.release_offline_guard()


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
    import ast

    banned = {
        2.2: "delineation.glacier_nir_swir1_ratio",
        0.104: "proxies.volume_area.huggel_2002.coeff",
        0.1217: "proxies.volume_area.cook_quincey_2015.coeff",
        1.4129: "proxies.volume_area.cook_quincey_2015.exp",
    }
    # Deliberately NOT banned: 1000.0 and 10000.0. Those are the ESA BOA
    # additive offset and quantification value - fixed properties of the
    # Sentinel-2 product format, not thresholds anyone would tune. Banning them
    # flagged five correct uses and taught nothing.
    # Parse rather than grep. The first version of this test matched raw text
    # and fired on a reflectance table inside a docstring - prose that
    # documents a threshold is exactly what we WANT, so a text match cannot
    # tell the difference. Walking the AST sees only real numeric literals.
    offenders = []
    for path in (REPO / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                    and not isinstance(node.value, bool):
                key = banned.get(float(node.value))
                if key:
                    offenders.append(
                        f"{path.relative_to(REPO)}:{node.lineno} literal "
                        f"{node.value} -> use cfg.require('{key}')")
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


def test_tool_output_dir_is_excluded_from_the_manifest(tmp_path):
    """A tool-built page must not enter the run manifest.

    outputs/interactive/map.html is built by tools/, not by `reproduce`. When it
    was written to outputs/ directly the manifest went from 44 artefacts to 46,
    which breaks two things at once: the manifest stops being a pure function of
    the run, and a container that never ran `make map` reports a spurious
    difference against a host that did.
    """
    from src.common.io import TOOL_OUTPUT_DIR

    (tmp_path / "stage00_thing.json").write_text("{}", encoding="utf-8")
    tool_dir = tmp_path / TOOL_OUTPUT_DIR
    tool_dir.mkdir()
    (tool_dir / "map.html").write_text("<p>built by a tool</p>", encoding="utf-8")
    (tool_dir / "map_data.json").write_text("{}", encoding="utf-8")

    # The default sweep still hashes everything: the exclusion is the
    # caller's decision, so that hashing data/pinned/ cannot lose a
    # directory that merely shares the name.
    assert set(manifest_for(tmp_path)) == {
        "stage00_thing.json",
        f"{TOOL_OUTPUT_DIR}/map.html",
        f"{TOOL_OUTPUT_DIR}/map_data.json",
    }
    m = manifest_for(tmp_path, exclude_top=(TOOL_OUTPUT_DIR,))
    assert set(m) == {"stage00_thing.json"}, m


def test_no_reproduce_stage_writes_into_the_unhashed_tool_dir():
    """The exclusion above is only safe while no stage writes there.

    Otherwise a stage could emit an artefact that the byte-identity check never
    sees, which is a hole in the guarantee rather than a convenience.
    """
    from src import stages as _impl  # noqa: F401  (import registers stages)
    from src.common.io import TOOL_OUTPUT_DIR
    from src.common.stages import reproduce_stages

    bad = [o for st in reproduce_stages() for o in (st.outputs or ())
           if o.replace("\\", "/").startswith(f"outputs/{TOOL_OUTPUT_DIR}/")]
    assert bad == [], bad
