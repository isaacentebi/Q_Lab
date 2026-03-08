from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
import uuid

from q_lab.models import utc_now

SAFETY_WARNING = (
    "Hyperliquid integration is paper-trading only in Q_Lab. "
    "Live trading and movement of real funds are disabled."
)


class LiveTradingDisabledError(RuntimeError):
    """Raised when a non-paper mode is requested."""


@dataclass(frozen=True)
class HyperliquidPaperConfig:
    mode: str = "paper"
    api_url: str = "https://api.hyperliquid.xyz"
    account_address: str | None = None


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    limit_price: float | None
    status: str
    created_at: str


class HyperliquidPaperAdapter:
    """Simulation-only adapter stub for future exchange abstraction."""

    def __init__(self, config: HyperliquidPaperConfig | None = None):
        self.config = config or HyperliquidPaperConfig()
        if self.config.mode.lower() != "paper":
            raise LiveTradingDisabledError(
                f"Requested mode '{self.config.mode}' is not allowed. {SAFETY_WARNING}"
            )

    @property
    def safety_warning(self) -> str:
        return SAFETY_WARNING

    def place_order(
        self,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        limit_price: float | None = None,
    ) -> PaperOrder:
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'")
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        return PaperOrder(
            order_id=f"paper-{uuid.uuid4().hex[:12]}",
            symbol=symbol,
            side=side,
            quantity=quantity,
            limit_price=limit_price,
            status="simulated",
            created_at=utc_now().isoformat(),
        )
