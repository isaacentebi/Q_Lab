from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class FeatureObservation:
    source: str
    timestamp: str
    values: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, str] = field(default_factory=dict)


class FeatureSource(Protocol):
    """Interface for exogenous feature providers used by strategies/evaluators."""

    name: str

    def describe(self) -> str: ...

    def fetch(self, market: str) -> Sequence[FeatureObservation]: ...


@dataclass(frozen=True)
class StaticFeatureSource:
    """Minimal source for MVP wiring and tests/documentation."""

    name: str
    description: str
    observations: Sequence[FeatureObservation] = field(default_factory=tuple)

    def describe(self) -> str:
        return self.description

    def fetch(self, market: str) -> Sequence[FeatureObservation]:
        _ = market
        return list(self.observations)


@dataclass(frozen=True)
class PolymarketFeatureSource(StaticFeatureSource):
    def __init__(self) -> None:
        super().__init__(
            name="polymarket",
            description=(
                "Prediction-market feature source for crowd-implied probabilities, "
                "probability change velocity, dispersion across related contracts, "
                "and event-resolution proximity."
            ),
        )


@dataclass(frozen=True)
class KalshiFeatureSource(StaticFeatureSource):
    def __init__(self) -> None:
        super().__init__(
            name="kalshi",
            description=(
                "Regulated event-market feature source for implied probabilities, "
                "spread/depth proxies, and cross-market disagreement signals."
            ),
        )
