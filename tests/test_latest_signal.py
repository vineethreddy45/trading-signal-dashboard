import pandas as pd

from src.strategy import StrategyConfig, latest_signal


def test_latest_signal_uses_latest_bar_date_not_historical_cross():
    index = pd.date_range("2024-01-01", periods=5, freq="D")
    df = pd.DataFrame(
        {
            "Open": [100, 105, 110, 108, 107],
            "High": [101, 106, 111, 109, 108],
            "Low": [99, 104, 109, 107, 106],
            "Close": [100, 110, 120, 115, 111],
            "Volume": [1200, 1500, 1700, 1300, 1400],
        },
        index=index,
    )

    signal = latest_signal(df, StrategyConfig(timeframe="Daily", market="USA"))

    assert signal["bar_date"] == "2024-01-05"
