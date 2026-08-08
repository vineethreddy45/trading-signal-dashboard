import unittest
from unittest.mock import patch

import pandas as pd

from src.market_data import _symbol_candidates
from src.strategy import StrategyConfig, backtest, enrich


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


class TestDojiSignals(unittest.TestCase):
    def test_double_doji_support_buy_signal(self):
        index = pd.date_range("2026-01-01", periods=25, freq="D")
        frame = pd.DataFrame(
            {
                "Open": [101.0] * 23 + [101.4, 101.6],
                "High": [103.0] * 23 + [102.0, 102.0],
                "Low": [100.0] * 23 + [100.0, 100.0],
                "Close": [101.5] * 23 + [101.45, 101.7],
                "Volume": [100.0] * 23 + [50.0, 55.0],
            },
            index=index,
        )
        cfg = StrategyConfig(timeframe="Daily", market="India")
        out = enrich(frame, cfg)
        self.assertTrue(bool(out.iloc[-1]["DOUBLE_DOJI_SUPPORT_BUY"]))
        self.assertEqual(str(out.iloc[-1]["SIGNAL"]), "DOUBLE DOJI SUPPORT BUY")

    def test_double_doji_resistance_alert_signal(self):
        index = pd.date_range("2026-02-01", periods=25, freq="D")
        frame = pd.DataFrame(
            {
                "Open": [112.0] * 23 + [114.2, 114.0],
                "High": [120.0] * 23 + [120.0, 120.0],
                "Low": [100.0] * 23 + [113.8, 113.6],
                "Close": [113.0] * 23 + [114.1, 113.9],
                "Volume": [100.0] * 23 + [50.0, 55.0],
            },
            index=index,
        )
        cfg = StrategyConfig(timeframe="Daily", market="India")
        out = enrich(frame, cfg)
        self.assertTrue(bool(out.iloc[-1]["DOUBLE_DOJI_RESISTANCE_ALERT"]))
        self.assertEqual(str(out.iloc[-1]["SIGNAL"]), "DOUBLE DOJI RESISTANCE ALERT")


if __name__ == "__main__":
    unittest.main()