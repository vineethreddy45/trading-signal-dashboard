import unittest
from unittest.mock import patch

import pandas as pd

from src.market_data import _symbol_candidates
from src.strategy import StrategyConfig, backtest


class TestMarketDataFallback(unittest.TestCase):
    def test_symbol_candidates_with_suffix(self):
        self.assertEqual(_symbol_candidates("RELIANCE.NS"), ["RELIANCE.NS", "RELIANCE"])

    def test_symbol_candidates_without_suffix(self):
        self.assertEqual(_symbol_candidates("AAPL"), ["AAPL", "AAPL.NS", "AAPL.BO"])


class TestBacktestTransactionCosts(unittest.TestCase):
    def test_backtest_reports_transaction_costs(self):
        index = pd.date_range("2026-01-01", periods=3, freq="D")
        enriched = pd.DataFrame(
            {
                "Open": [100.0, 100.0, 100.0],
                "High": [100.0, 140.0, 100.0],
                "Low": [99.0, 99.0, 99.0],
                "Close": [100.0, 110.0, 110.0],
                "EMA30": [95.0, 95.0, 95.0],
                "BREAKOUT_BUY": [True, False, False],
                "STOP": [95.0, 95.0, 95.0],
            },
            index=index,
        )

        cfg = StrategyConfig(
            timeframe="Daily",
            capital=10_000,
            risk_pct=1.0,
            target_r=2.0,
            commission_pct=0.10,
            slippage_pct=0.10,
        )

        with patch("src.strategy.enrich", return_value=enriched):
            trades, equity, metrics = backtest(enriched, cfg)

        self.assertFalse(trades.empty)
        self.assertIn("costs", trades.columns)
        self.assertGreater(metrics["total_costs"], 0.0)
        self.assertGreater(len(equity), 0)


if __name__ == "__main__":
    unittest.main()