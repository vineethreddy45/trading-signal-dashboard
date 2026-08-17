from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import yfinance as yf

from src.market_data import download_history
from src.strategy import StrategyConfig, convert_timeframe, enrich, latest_signal, latest_signal_row


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


def get_ticker_profile(symbol: str) -> tuple[float | None, str, str]:
    ticker = yf.Ticker(symbol)
    info = getattr(ticker, "info", {}) or {}

    market_cap = info.get("marketCap")
    if market_cap is None:
        fast = getattr(ticker, "fast_info", {}) or {}
        market_cap = fast.get("market_cap")

    sector = str(info.get("sector") or "Unknown").strip() or "Unknown"
    industry = str(info.get("industry") or "Unknown").strip() or "Unknown"
    return (float(market_cap) if market_cap is not None else None, sector, industry)


def format_market_cap(value: float | int | None) -> str:
    if value is None or value <= 0:
        return "N/A"
    for suffix, divisor in [("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000)]:
        if value >= divisor:
            return f"{value / divisor:.1f}{suffix}"
    return f"{value:,.0f}"


def signal_distance_components(row: pd.Series, signal_name: str) -> float:
    _ = signal_name

    close = float(row.get("Close", 0.0) or 0.0)
    ema20 = float(row.get("EMA20", 0.0) or 0.0)
    dist_ema20_pct = ((close - ema20) / ema20 * 100.0) if ema20 > 0 else 0.0
    return float(dist_ema20_pct)


def scan_symbols(symbols_df: pd.DataFrame, timeframe: str, limit: int | None = None) -> pd.DataFrame:
    rows, source = [], symbols_df.head(limit) if limit else symbols_df
    for item in source.itertuples(index=False):
        try:
            quote_symbol = str(item.symbol).strip().upper()
            display_symbol = str(item.display_symbol).strip().upper()
            if not quote_symbol:
                raise ValueError("Missing symbol")

            cfg = StrategyConfig(
                timeframe=timeframe,
                market=item.market,
            )
            daily = download_history(quote_symbol, "1y")
            bars = convert_timeframe(daily, timeframe)
            enriched_bars = enrich(bars, cfg)
            signal = latest_signal(bars, cfg)
            row = latest_signal_row(enriched_bars)
            dist_ema20_pct = signal_distance_components(row, signal["signal"])
            market_cap, sector, industry = get_ticker_profile(quote_symbol)
            bucket = market_cap_bucket(market_cap)
            signal_name = signal["signal"]
            rows.append({
                "Symbol": display_symbol,
                "Quote Symbol": quote_symbol,
                "Market": item.market,
                "Sector": sector,
                "Industry": industry,
                "Market Cap": format_market_cap(market_cap),
                "Market Cap Value": market_cap,
                "Market Cap Bucket": bucket,
                "Signal": signal_name,
                "Error": "",
                "Close": signal["close"],
                "EMA20": signal["ema20"],
                "EMA30": signal["ema30"],
                "Volume Confirm": False,
                "Close > EMA20": signal["above_ema20"],
                "Close > EMA30": signal["above_ema30"],
                "EMA20 > EMA30": signal["ema_stack"],
                "Bar Date": signal["bar_date"],
                "Distance to EMA20 %": dist_ema20_pct,
            })
        except Exception as exc:
            rows.append({
                "Symbol": str(item.display_symbol).strip().upper(),
                "Quote Symbol": str(item.symbol).strip().upper(),
                "Market": item.market,
                "Sector": "Unknown",
                "Industry": "Unknown",
                "Market Cap": "N/A",
                "Market Cap Value": None,
                "Market Cap Bucket": "Unknown",
                "Signal": "AVOID",
                "Error": str(exc),
                "Close": None,
                "EMA20": None,
                "EMA30": None,
                "Volume Confirm": False,
                "Close > EMA20": False,
                "Close > EMA30": False,
                "EMA20 > EMA30": False,
                "Bar Date": None,
                "Distance to EMA20 %": 0.0,
            })
    result = pd.DataFrame(rows)
    order = {
        "BREAKOUT BUY": 1,
        "PULLBACK BUY": 2,
        "DOUBLE DOJI SUPPORT BUY": 3,
        "WATCH": 4,
        "NEUTRAL": 5,
        "DOUBLE DOJI RESISTANCE ALERT": 6,
        "AVOID": 7,
        "ERROR": 9,
    }
    result["_rank"] = result["Signal"].map(order).fillna(99)
    result = result.sort_values(["_rank", "Market", "Symbol"], ascending=[True, True, True])
    return result.drop(columns="_rank")
