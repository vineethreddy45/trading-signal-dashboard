import pandas as pd

from src.scanner import scan_symbols, signal_distance_components


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


def test_scan_symbols_skips_invalid_yahoo_symbols():
    symbols_df = pd.DataFrame(
        [
            {
                "symbol": "AKZOINDIA.NS",
                "market": "India",
                "display_symbol": "AKZOINDIA",
            }
        ]
    )

    result = scan_symbols(symbols_df, "Daily")

    assert result.empty
