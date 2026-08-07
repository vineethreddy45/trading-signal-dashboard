from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf

from src.market_data import download_history
from src.strategy import StrategyConfig, convert_timeframe, enrich, latest_signal


MARKET_CAP_BUCKETS = {
    "Mega Cap": 200_000_000_000,
    "Large Cap": 10_000_000_000,
    "Mid Cap": 2_000_000_000,
}


def market_cap_bucket(market_cap: float | int | None) -> str:
    if market_cap is None or market_cap <= 0:
        return "Unknown"
    if market_cap >= MARKET_CAP_BUCKETS["Mega Cap"]:
        return "Mega Cap"
    if market_cap >= MARKET_CAP_BUCKETS["Large Cap"]:
        return "Large Cap"
    if market_cap >= MARKET_CAP_BUCKETS["Mid Cap"]:
        return "Mid Cap"
    return "Small Cap"


def get_market_cap(symbol: str) -> float | None:
    ticker = yf.Ticker(symbol)
    info = getattr(ticker, "info", {}) or {}
    market_cap = info.get("marketCap")
    if market_cap is None:
        fast = getattr(ticker, "fast_info", {}) or {}
        market_cap = fast.get("market_cap")
    return float(market_cap) if market_cap is not None else None


def format_market_cap(value: float | int | None) -> str:
    if value is None or value <= 0:
        return "N/A"
    for suffix, divisor in [("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000)]:
        if value >= divisor:
            return f"{value / divisor:.1f}{suffix}"
    return f"{value:,.0f}"


def setup_score_components(row: pd.Series, signal_name: str) -> tuple[float, float, float, float]:
    signal_bonus = {
        "BREAKOUT BUY": 40.0,
        "PULLBACK BUY": 32.0,
        "WATCH": 20.0,
        "NEUTRAL": 10.0,
        "AVOID": 0.0,
        "ERROR": 0.0,
    }.get(signal_name, 0.0)

    trend_score = (
        int(bool(row.get("ABOVE_EMA20", False)))
        + int(bool(row.get("ABOVE_EMA30", False)))
        + int(bool(row.get("EMA_STACK", False)))
        + int(bool(row.get("EMA20_RISING", False)))
        + int(bool(row.get("EMA30_RISING", False)))
    )

    vol_avg = float(row.get("VOL_AVG20", 0.0) or 0.0)
    volume = float(row.get("Volume", 0.0) or 0.0)
    volume_ratio = (volume / vol_avg) if vol_avg > 0 else 0.0

    close = float(row.get("Close", 0.0) or 0.0)
    ema20 = float(row.get("EMA20", 0.0) or 0.0)
    dist_ema20_pct = ((close - ema20) / ema20 * 100.0) if ema20 > 0 else 0.0

    score = signal_bonus + trend_score * 8.0 + min(max(volume_ratio, 0.0), 2.5) * 8.0 - min(abs(dist_ema20_pct), 12.0)
    score = float(max(0.0, min(100.0, score)))
    return score, float(trend_score), float(volume_ratio), float(dist_ema20_pct)


def scan_symbols(symbols_df: pd.DataFrame, timeframe: str, limit: int | None = None) -> pd.DataFrame:
    rows, source = [], symbols_df.head(limit) if limit else symbols_df
    for item in source.itertuples(index=False):
        try:
            quote_symbol = str(item.symbol).strip().upper()
            display_symbol = str(item.display_symbol).strip().upper()
            if not quote_symbol:
                raise ValueError("Missing symbol")

            cfg = StrategyConfig(timeframe=timeframe, market=item.market)
            daily = download_history(quote_symbol, "1y")
            bars = convert_timeframe(daily, timeframe)
            enriched_bars = enrich(bars, cfg)
            signal = latest_signal(bars, cfg)
            row = enriched_bars.iloc[-1]
            score, trend_score, volume_ratio, dist_ema20_pct = setup_score_components(row, signal["signal"])
            market_cap = get_market_cap(quote_symbol)
            bucket = market_cap_bucket(market_cap)
            rows.append({
                "Symbol": display_symbol,
                "Quote Symbol": quote_symbol,
                "Market": item.market,
                "Market Cap": format_market_cap(market_cap),
                "Market Cap Value": market_cap,
                "Market Cap Bucket": bucket,
                "Signal": signal["signal"],
                "Error": "",
                "Close": signal["close"],
                "EMA20": signal["ema20"],
                "EMA30": signal["ema30"],
                "Volume Confirm": signal["volume_confirm"],
                "Close > EMA20": signal["above_ema20"],
                "Close > EMA30": signal["above_ema30"],
                "EMA20 > EMA30": signal["ema_stack"],
                "Bar Date": signal["bar_date"],
                "Setup Score": score,
                "Trend Score": trend_score,
                "Volume Ratio": volume_ratio,
                "Distance to EMA20 %": dist_ema20_pct,
            })
        except Exception as exc:
            rows.append({
                "Symbol": str(item.display_symbol).strip().upper(),
                "Quote Symbol": str(item.symbol).strip().upper(),
                "Market": item.market,
                "Market Cap": "N/A",
                "Market Cap Value": None,
                "Market Cap Bucket": "Unknown",
                "Signal": "ERROR",
            "Error": str(exc),
                "Close": None,
                "EMA20": None,
                "EMA30": None,
                "Volume Confirm": False,
                "Close > EMA20": False,
                "Close > EMA30": False,
                "EMA20 > EMA30": False,
                "Bar Date": None,
                "Setup Score": 0.0,
                "Trend Score": 0.0,
                "Volume Ratio": 0.0,
                "Distance to EMA20 %": 0.0,
            })
    result = pd.DataFrame(rows)
    order = {"BREAKOUT BUY": 1, "PULLBACK BUY": 2, "WATCH": 3, "NEUTRAL": 4, "AVOID": 5, "ERROR": 9}
    result["_rank"] = result["Signal"].map(order).fillna(99)
    result = result.sort_values(["Setup Score", "_rank", "Market", "Symbol"], ascending=[False, True, True, True])
    return result.drop(columns="_rank")
