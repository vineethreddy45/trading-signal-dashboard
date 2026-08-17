import numpy as np
import pandas as pd

from src.strategy import StrategyConfig, latest_signal, latest_signal_row


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


def test_latest_signal_uses_max_index_date_even_if_last_row_is_not_latest():
    df = pd.DataFrame(
        {
            "Open": [100, 105, 110],
            "High": [101, 106, 111],
            "Low": [99, 104, 109],
            "Close": [100, 110, 120],
            "Volume": [1200, 1500, 1700],
        },
        index=pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"]),
    )

    signal = latest_signal(df, StrategyConfig(timeframe="Daily", market="USA"))

    assert signal["bar_date"] == "2024-01-03"


def test_latest_signal_row_ignores_dates_without_valid_ema_values():
    df = pd.DataFrame(
        {
            "EMA20": [np.nan, 100.0, 101.0, 102.0, np.nan],
            "EMA30": [np.nan, 99.0, 100.0, 101.0, np.nan],
            "SIGNAL": ["AVOID", "WATCH", "WATCH", "BREAKOUT BUY", "AVOID"],
            "Close": [10.0, 12.0, 13.0, 14.0, 15.0],
            "VOLUME_CONFIRM": [False, True, True, True, False],
            "ABOVE_EMA20": [False, True, True, True, False],
            "ABOVE_EMA30": [False, True, True, True, False],
            "EMA_STACK": [False, True, True, True, False],
        },
        index=pd.to_datetime([
            "2024-01-01",
            "2024-01-02",
            "2024-01-03",
            "2024-01-04",
            "2024-01-05",
        ]),
    )

    row = latest_signal_row(df)

    assert str(row.name.date()) == "2024-01-04"


def test_latest_signal_removes_volume_confirm_for_non_bullish_states():
    df = pd.DataFrame(
        {
            "Open": [100, 105],
            "High": [101, 106],
            "Low": [99, 104],
            "Close": [100, 110],
            "Volume": [1000, 2000],
            "EMA20": [100.0, 105.0],
            "EMA30": [99.0, 104.0],
            "VOLUME_CONFIRM": [True, True],
            "ABOVE_EMA20": [False, True],
            "ABOVE_EMA30": [False, True],
            "EMA_STACK": [False, True],
            "SIGNAL": ["WATCH", "NEUTRAL"],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
    )

    assert latest_signal(df, StrategyConfig(timeframe="Daily", market="USA"))["volume_confirm"] is False
