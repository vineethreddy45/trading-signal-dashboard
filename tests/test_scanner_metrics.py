import pandas as pd

from src.scanner import signal_distance_components


def test_signal_distance_components_returns_ema_distance_without_setup_score():
    row = pd.Series(
        {
            "Close": 110.0,
            "EMA20": 100.0,
        }
    )

    result = signal_distance_components(row, "BREAKOUT BUY")

    assert isinstance(result, float)
    assert result == 10.0
