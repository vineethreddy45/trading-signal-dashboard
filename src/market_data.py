from __future__ import annotations
import time

import pandas as pd
import yfinance as yf


def _symbol_candidates(symbol: str) -> list[str]:
    base = str(symbol).strip().upper()
    if not base:
        return []

    candidates = [base]
    if base.endswith(".NS") or base.endswith(".BO"):
        candidates.append(base.rsplit(".", 1)[0])
    elif "." not in base:
        candidates.extend([f"{base}.NS", f"{base}.BO"])

    # Preserve order and remove duplicates.
    return list(dict.fromkeys(candidates))


def _download_with_retries(symbol: str, period: str, attempts: int = 3) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            data = yf.download(
                symbol,
                period=period,
                interval="1d",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if not data.empty:
                return data
        except Exception as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(0.4 * attempt)

    if last_error is not None:
        raise last_error
    return pd.DataFrame()


def _history_with_fallback(symbol: str, period: str, interval: str) -> pd.DataFrame:
    last_error: Exception | None = None
    for candidate in _symbol_candidates(symbol):
        try:
            data = yf.Ticker(candidate).history(period=period, interval=interval, auto_adjust=True)
            if not data.empty:
                return data
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return pd.DataFrame()


def download_history(symbol: str, period: str = "5y") -> pd.DataFrame:
    data = pd.DataFrame()
    for candidate in _symbol_candidates(symbol):
        data = _download_with_retries(candidate, period=period, attempts=3)
        if not data.empty:
            break
    if data.empty:
        raise ValueError(f"No data returned for {symbol}")
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in data.columns]
    if missing:
        raise ValueError(f"{symbol}: missing columns {missing}")
    return data[required].dropna(subset=["Close"]).copy()


def latest_price(symbol: str) -> tuple[float, str]:
    data = _history_with_fallback(symbol, period="5d", interval="1m")
    if data.empty:
        data = _history_with_fallback(symbol, period="5d", interval="1d")
    if data.empty:
        raise ValueError(f"No latest quote for {symbol}")
    data = data.dropna(subset=["Close"])
    return float(data.iloc[-1]["Close"]), str(data.index[-1])
