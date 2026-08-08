import unittest

import pandas as pd

from src.strategy import convert_timeframe


class TestTimeframeConversion(unittest.TestCase):
    def test_monthly_and_quarterly_conversion(self):
        idx = pd.date_range("2026-01-01", periods=120, freq="D")
        daily = pd.DataFrame(
            {
                "Open": [100.0 + i * 0.1 for i in range(len(idx))],
                "High": [101.0 + i * 0.1 for i in range(len(idx))],
                "Low": [99.0 + i * 0.1 for i in range(len(idx))],
                "Close": [100.5 + i * 0.1 for i in range(len(idx))],
                "Volume": [1_000 + i for i in range(len(idx))],
            },
            index=idx,
        )

        monthly = convert_timeframe(daily, "Monthly")
        quarterly = convert_timeframe(daily, "Quarterly")

        self.assertGreater(len(monthly), 0)
        self.assertGreater(len(quarterly), 0)
        self.assertLessEqual(len(quarterly), len(monthly))
        self.assertTrue({"Open", "High", "Low", "Close", "Volume"}.issubset(monthly.columns))


if __name__ == "__main__":
    unittest.main()
