from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf

from src.market_data import download_history
from src.strategy import StrategyConfig, convert_timeframe, latest_signal


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
            signal = latest_signal(convert_timeframe(daily, timeframe), cfg)
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
            })
    result = pd.DataFrame(rows)
    order = {"BREAKOUT BUY": 1, "PULLBACK BUY": 2, "WATCH": 3, "NEUTRAL": 4, "AVOID": 5, "ERROR": 9}
    result["_rank"] = result["Signal"].map(order).fillna(99)
    return result.sort_values(["_rank", "Market", "Symbol"]).drop(columns="_rank")
