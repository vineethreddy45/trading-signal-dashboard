from __future__ import annotations
import pandas as pd
import yfinance as yf


def download_history(symbol: str, period: str = "5y") -> pd.DataFrame:
    data = yf.download(symbol, period=period, interval="1d", auto_adjust=True, progress=False, threads=False)
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
    data = yf.Ticker(symbol).history(period="5d", interval="1m", auto_adjust=True)
    if data.empty:
        data = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=True)
    if data.empty:
        raise ValueError(f"No latest quote for {symbol}")
    data = data.dropna(subset=["Close"])
    return float(data.iloc[-1]["Close"]), str(data.index[-1])
