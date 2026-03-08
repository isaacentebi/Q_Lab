import unittest

from q_lab.adapters.hyperliquid import (
    HyperliquidPaperAdapter,
    HyperliquidPaperConfig,
    LiveTradingDisabledError,
    SAFETY_WARNING,
)


class TestHyperliquidAdapter(unittest.TestCase):
    def test_hyperliquid_adapter_rejects_non_paper_mode(self):
        with self.assertRaises(LiveTradingDisabledError):
            HyperliquidPaperAdapter(HyperliquidPaperConfig(mode="live"))

    def test_hyperliquid_adapter_simulates_order(self):
        adapter = HyperliquidPaperAdapter(HyperliquidPaperConfig(mode="paper"))
        order = adapter.place_order("BTC-USD", "buy", quantity=0.1, limit_price=50000.0)
        self.assertEqual(order.status, "simulated")
        self.assertTrue(order.order_id.startswith("paper-"))
        self.assertEqual(adapter.safety_warning, SAFETY_WARNING)


if __name__ == "__main__":
    unittest.main()
