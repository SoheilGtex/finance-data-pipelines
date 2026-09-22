from __future__ import annotations

from dataclasses import replace

import pytest

from fdp.extract import generate_synthetic
from fdp.model import PriceEvent


@pytest.fixture
def base_events() -> tuple[PriceEvent, ...]:
    return generate_synthetic(rows=12, seed=20270916)


@pytest.fixture
def changed_events(base_events: tuple[PriceEvent, ...]) -> tuple[PriceEvent, ...]:
    first = base_events[0]
    updated = replace(
        first,
        revision=2,
        close_micros=first.close_micros + 500,
    )
    return (*base_events, updated)


def raise_at(target: str):
    def hook(stage: str) -> None:
        if stage == target:
            raise RuntimeError(f"injected failure at {stage}")

    return hook
