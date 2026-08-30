"""Entry point. `python -m src.cli <command>`

Commands:
  reproduce            run every reproduce-safe stage end-to-end, offline
  stage N              run a single stage
  verify-determinism   run reproduce twice into separate trees and diff hashes
  list-stages          show what is implemented vs. still pending
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from src.common import determinism as det
from src.common.config import REPO_ROOT, load_config


def _bootstrap(cfg):
    """Order matters: thread limits before numpy import, seeds before anything."""
    det.set_thread_limits(cfg.require("determinism.thread_limit"))
    det.verify_hash_seed(cfg.require("determinism.python_hash_seed"))
    det.seed_everything(cfg.require("determinism.seed"))


def _run_stages(cfg, stages, offline: bool) -> dict:
    if offline:
        det.engage_offline_guard()
    results = {}
    for st in stages:
        print(f"[stage {st.number:02d}] {st.title} ...", flush=True)
        summary = st.fn(cfg)
        results[f"stage{st.number:02d}_{st.slug}"] = summary or {}
        print(f"[stage {st.number:02d}] ok  {summary}", flush=True)
    return results


def cmd_reproduce(args) -> int:
    cfg = load_config()
    _bootstrap(cfg)
    from src import stages as _impl  # noqa: F401  (import registers stages)
    from src.common.stages import reproduce_stages

    from src.common.io import manifest_for, write_json

    out_dir = REPO_ROOT / "outputs"
    results = _run_stages(cfg, reproduce_stages(), offline=cfg.require("determinism.enforce_offline"))

    # The manifest is written last and excludes itself, so it is a pure
    # function of the run's artefacts.
    manifest_path = out_dir / "run_manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
    write_json(manifest_path, {
        "frozen_clock_utc": cfg.require("determinism.frozen_utc"),
        "stages_run": sorted(results),
        "stage_summaries": results,
        "artefact_sha256": manifest_for(out_dir),
    })
    print(f"\nreproduce complete -> {manifest_path.relative_to(REPO_ROOT).as_posix()}")
    return 0


def cmd_stage(args) -> int:
    cfg = load_config()
    _bootstrap(cfg)
    from src import stages as _impl  # noqa: F401
    from src.common.stages import get_stage

    st = get_stage(args.number)
    _run_stages(cfg, [st], offline=st.reproduce_safe and cfg.require("determinism.enforce_offline"))
    return 0


def cmd_list_stages(args) -> int:
    load_config()
    from src import stages as _impl  # noqa: F401
    from src.common.stages import all_stages

    implemented = {s.number: s for s in all_stages()}
    # Titles come from the plan; a stage with no implementation prints as
    # pending so progress is never overstated.
    plan = {
        0: "Repository, environment, and determinism scaffolding",
        1: "Pinned dataset and ground-truth labels",
        2: "Watcher: deterministic lake delineation",
        3: "Watcher: multi-date trajectory + burst detection",
        4: "Watcher: dam-failure and mass-movement proxy engine",
        5: "Watcher: exposure overlay and asset criticality",
        6: "Watcher: flow routing / indicative inundation path",
        7: "Watcher eval: baseline vs. proxy-augmented",
        8: "Reporter: retriever agent",
        9: "Reporter: numeric-reconciliation agent",
        10: "Reporter: drafting agent (OCHA bilingual sitrep)",
        11: "Reporter: adversarial critic + NLI verification",
        12: "Reporter: provenance ledger + human approval",
        13: "CAP XML + HXL-tagged CSV outputs",
        14: "Reporter eval: baseline vs. advanced",
        15: "Nepali translation and terminology QA",
        16: "Negative-control and confusion-matrix validation",
        17: "Reproducibility packaging",
        18: "Documentation, limits/ethics, final packaging",
    }
    for n, title in plan.items():
        mark = "DONE   " if n in implemented else "pending"
        print(f"  [{mark}] stage {n:02d}  {title}")
    print(f"\n{len(implemented)}/{len(plan)} stages implemented")
    return 0


def cmd_verify_determinism(args) -> int:
    """Run reproduce twice into isolated trees and compare artefact hashes.

    Run twice in *separate processes* on purpose: an in-process rerun would
    reuse warmed caches and could hide a nondeterminism that only shows on a
    cold start.
    """
    import subprocess
    import os

    from src.common.io import read_json

    cfg = load_config()
    env = dict(os.environ, PYTHONHASHSEED=str(cfg.require("determinism.python_hash_seed")))
    tmp = REPO_ROOT / ".determinism_check"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    manifests = []
    for i in (1, 2):
        r = subprocess.run([sys.executable, "-m", "src.cli", "reproduce"],
                           cwd=REPO_ROOT, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout); print(r.stderr, file=sys.stderr)
            print(f"FAIL: reproduce run {i} exited {r.returncode}")
            return 1
        snap = tmp / f"run{i}_manifest.json"
        shutil.copy(REPO_ROOT / "outputs" / "run_manifest.json", snap)
        manifests.append(read_json(snap)["artefact_sha256"])
        print(f"  run {i}: {len(manifests[-1])} artefacts hashed")

    a, b = manifests
    diffs = sorted(set(a) ^ set(b)) + sorted(k for k in set(a) & set(b) if a[k] != b[k])
    if diffs:
        print("\nFAIL: outputs are not byte-identical across runs:")
        for k in diffs:
            print(f"  {k}: {a.get(k, '<absent>')[:12]} != {b.get(k, '<absent>')[:12]}")
        return 1
    print(f"\nPASS: {len(a)} artefacts byte-identical across two cold runs")
    shutil.rmtree(tmp)
    return 0



def cmd_approve(args) -> int:
    """Interactive approval. Deliberately NOT reproduce-safe.

    The offline guard is not engaged and the frozen clock is not imposed,
    because this is an operator tool rather than part of the reproducible run.
    It writes only to data/approvals/, which reproduce reads and never writes.
    """
    from src.reporter.approve_cli import main as approve_main
    argv = []
    if getattr(args, "draft", None):
        argv += ["--draft", args.draft]
    if getattr(args, "list", False):
        argv += ["--list"]
    return approve_main(argv)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="glof", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("reproduce").set_defaults(func=cmd_reproduce)
    ap = sub.add_parser(
        "approve",
        help="INTERACTIVE human-approval checkpoint (never part of reproduce)")
    ap.add_argument("--draft", help="decide a single draft, e.g. thame_2024_en")
    ap.add_argument("--list", action="store_true",
                    help="show decision status and exit")
    ap.set_defaults(func=cmd_approve)

    sub.add_parser("list-stages").set_defaults(func=cmd_list_stages)
    sub.add_parser("verify-determinism").set_defaults(func=cmd_verify_determinism)
    sp = sub.add_parser("stage"); sp.add_argument("number", type=int)
    sp.set_defaults(func=cmd_stage)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
