"""Stage implementations, registered in plan order.

Stages 1-18 land here as they are built. Stage 0 registers the environment
self-check, which is a real gate: it fails the run if determinism guarantees
are not actually in force.
"""
from __future__ import annotations

from pathlib import Path

from src.common.config import REPO_ROOT, Config
from src.common.determinism import environment_fingerprint, offline_engaged
from src.common.io import sha256_file, write_json
from src.common.stages import stage

# Directories every later stage assumes exist. Checked, not created blindly -
# a missing data dir should be visible, not silently papered over.
REQUIRED_DIRS = (
    "src/watcher", "src/reporter", "src/eval",
    "data/pinned", "data/labels", "docs", "outputs", "config",
)


@stage(0, "scaffold", "Repository, environment, and determinism scaffolding",
       outputs=("outputs/stage00_environment.json",))
def stage00_scaffold(cfg: Config) -> dict:
    """Verify the determinism contract holds, then record it.

    This is deliberately a *gate*, not a no-op: if the offline guard is not
    engaged or a required directory is missing, reproduce fails here rather
    than producing an output that quietly means nothing.
    """
    missing = [d for d in REQUIRED_DIRS if not (REPO_ROOT / d).is_dir()]
    if missing:
        raise RuntimeError(f"required directories missing: {missing}")

    if cfg.require("determinism.enforce_offline") and not offline_engaged():
        raise RuntimeError(
            "offline guard is not engaged but config demands it; "
            "reproduce would not actually prove the no-network claim"
        )

    # Hash the inputs that define the run. If a reviewer's numbers differ from
    # ours, the first question is whether these three files match.
    inputs = {}
    for rel in ("config/config.yaml", "requirements.txt", "requirements-lock.txt"):
        p = REPO_ROOT / rel
        inputs[rel] = sha256_file(p) if p.is_file() else None

    record = {
        "stage": 0,
        "environment": environment_fingerprint(),
        "seeds": {
            "seed": cfg.require("determinism.seed"),
            "python_hash_seed": cfg.require("determinism.python_hash_seed"),
            "llm_temperature": cfg.require("llm.temperature"),
            "llm_seed": cfg.require("llm.seed"),
        },
        "frozen_clock_utc": cfg.require("determinism.frozen_utc"),
        "offline_guard_engaged": offline_engaged(),
        "input_hashes": inputs,
        "directories_present": list(REQUIRED_DIRS),
    }
    write_json(REPO_ROOT / "outputs" / "stage00_environment.json", record)
    return {"checks_passed": len(REQUIRED_DIRS) + 1, "artefacts": 1}
