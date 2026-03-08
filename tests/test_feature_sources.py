import unittest

from q_lab.features import KalshiFeatureSource, PolymarketFeatureSource


class FeatureSourceTests(unittest.TestCase):
    def test_polymarket_source_has_expected_name(self) -> None:
        source = PolymarketFeatureSource()
        self.assertEqual(source.name, "polymarket")
        self.assertIn("implied probabilities", source.describe())
        self.assertEqual(source.fetch("BTC"), [])

    def test_kalshi_source_has_expected_name(self) -> None:
        source = KalshiFeatureSource()
        self.assertEqual(source.name, "kalshi")
        self.assertIn("event-market", source.describe())
        self.assertEqual(source.fetch("ETH"), [])


if __name__ == "__main__":
    unittest.main()
