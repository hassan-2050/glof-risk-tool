"""Stage registry.

The plan is gated stage-by-stage, so the code is too: each stage registers
itself with the id from the plan, declares which outputs it produces, and the
runner executes them in order. Adding Stage N+1 means adding one decorated
function - never editing the runner.

A stage that is declared but not yet implemented registers as `pending`, so
`make reproduce` reports honest progress instead of silently skipping work.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Iterable

StageFn = Callable[..., dict]


@dataclasses.dataclass(frozen=True)
class Stage:
    number: int
    slug: str
    title: str
    fn: StageFn
    outputs: tuple[str, ...] = ()
    # Stages needing network (Stage 1 fetch) are excluded from `reproduce`.
    reproduce_safe: bool = True


_REGISTRY: dict[int, Stage] = {}


def stage(number: int, slug: str, title: str, outputs: Iterable[str] = (),
          reproduce_safe: bool = True):
    def deco(fn: StageFn) -> StageFn:
        if number in _REGISTRY:
            raise ValueError(f"stage {number} already registered "
                             f"({_REGISTRY[number].slug})")
        _REGISTRY[number] = Stage(number, slug, title, fn, tuple(outputs),
                                  reproduce_safe)
        return fn
    return deco


def all_stages() -> list[Stage]:
    return [_REGISTRY[n] for n in sorted(_REGISTRY)]


def reproduce_stages() -> list[Stage]:
    return [s for s in all_stages() if s.reproduce_safe]


def get_stage(number: int) -> Stage:
    if number not in _REGISTRY:
        raise KeyError(f"stage {number} is not registered. Registered: "
                       f"{sorted(_REGISTRY)}")
    return _REGISTRY[number]
