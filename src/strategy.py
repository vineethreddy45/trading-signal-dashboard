from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrategyConfig:
    timeframe: str = "Weekly"
    stop_lookback: int = 2
    target_r: float = 2.0
    capital: float = 1_000_000
    risk_pct: float = 1.0
    commission_pct: float = 0.05
    slippage_pct: float = 0.05
    market: str = "USA"


def convert_timeframe(daily: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if timeframe == "Daily":
        return daily.copy()
    return daily.resample("W-FRI").agg(
        Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
        Close=("Close", "last"), Volume=("Volume", "sum")
    ).dropna()


def enrich(data: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    df = data.copy()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA30"] = df["Close"].ewm(span=30, adjust=False).mean()
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()
    df["ABOVE_EMA20"] = df["Close"] > df["EMA20"]
    df["ABOVE_EMA30"] = df["Close"] > df["EMA30"]
    df["EMA_STACK"] = df["EMA20"] > df["EMA30"]
    df["EMA20_RISING"] = df["EMA20"] > df["EMA20"].shift(1)
    df["EMA30_RISING"] = df["EMA30"] > df["EMA30"].shift(1)
    df["VOLUME_CONFIRM"] = df["Volume"] > df["VOL_AVG20"]
    df["PRIOR_HIGH"] = df["High"].shift(1)
    df["STOP"] = df["Low"].rolling(cfg.stop_lookback).min().shift(1)
    if cfg.market == "USA":
        df["BREAKOUT_BUY"] = (
            (df["ABOVE_EMA20"] | df["ABOVE_EMA30"]) & df["EMA_STACK"] &
            ((df["EMA20_RISING"] & df["EMA30_RISING"]) | df["VOLUME_CONFIRM"]) &
            (df["Close"] > df["PRIOR_HIGH"])
        )
        df["PULLBACK_BUY"] = (
            (df["ABOVE_EMA30"] | df["ABOVE_EMA20"]) & df["EMA_STACK"] &
            (df["Low"] <= df["EMA20"]) & (df["Close"] > df["EMA20"]) &
            (df["VOLUME_CONFIRM"] | df["EMA20_RISING"])
        )
    else:
        df["BREAKOUT_BUY"] = (
            df["ABOVE_EMA20"] & df["ABOVE_EMA30"] & df["EMA_STACK"] &
            df["EMA20_RISING"] & df["EMA30_RISING"] & df["VOLUME_CONFIRM"] &
            (df["Close"] > df["PRIOR_HIGH"])
        )
        df["PULLBACK_BUY"] = (
            df["ABOVE_EMA30"] & df["EMA_STACK"] & (df["Low"] <= df["EMA20"]) &
            (df["Close"] > df["EMA20"]) & df["VOLUME_CONFIRM"]
        )
    score = (df["ABOVE_EMA20"].astype(int) + df["ABOVE_EMA30"].astype(int) +
             df["EMA_STACK"].astype(int) + df["EMA20_RISING"].astype(int) +
             df["EMA30_RISING"].astype(int) + df["VOLUME_CONFIRM"].astype(int))
    df["SIGNAL"] = np.select(
        [df["BREAKOUT_BUY"], df["PULLBACK_BUY"], score >= 5, score >= 3],
        ["BREAKOUT BUY", "PULLBACK BUY", "WATCH", "NEUTRAL"],
        default="AVOID",
    )
    return df


def latest_signal(data: pd.DataFrame, cfg: StrategyConfig) -> dict:
    df = enrich(data, cfg)
    row = df.iloc[-1]
    above = df["ABOVE_EMA20"]

    if row["ABOVE_EMA20"]:
        cross = df.loc[above & ~above.shift(1).fillna(False)]
        bar_date = cross.index[-1].date() if not cross.empty else row.name.date()
    else:
        above_ema20 = df.loc[above]
        bar_date = above_ema20.index[-1].date() if not above_ema20.empty else row.name.date()

    return {
        "signal": str(row["SIGNAL"]), "close": float(row["Close"]),
        "ema20": float(row["EMA20"]), "ema30": float(row["EMA30"]),
        "volume_confirm": bool(row["VOLUME_CONFIRM"]),
        "above_ema20": bool(row["ABOVE_EMA20"]),
        "above_ema30": bool(row["ABOVE_EMA30"]),
        "ema_stack": bool(row["EMA_STACK"]),
        "bar_date": str(bar_date),
    }


def backtest(data: pd.DataFrame, cfg: StrategyConfig):
    df = enrich(data, cfg)
    cash, position, trades, equity = cfg.capital, None, [], []
    friction = (cfg.commission_pct + cfg.slippage_pct) / 100
    for i in range(1, len(df)):
        date, row, prev = df.index[i], df.iloc[i], df.iloc[i-1]
        if position is None and bool(prev["BREAKOUT_BUY"]):
            entry, stop = float(row["Open"]) * (1 + friction), float(prev["STOP"])
            if np.isfinite(stop) and 0 < stop < entry:
                risk_per_share = entry - stop
                qty = min(int((cash * cfg.risk_pct / 100) // risk_per_share), int(cash // entry))
                if qty > 0:
                    position = {"entry_date": date, "entry": entry, "stop": stop,
                                "target": entry + cfg.target_r * risk_per_share, "quantity": qty}
        if position:
            exit_price, reason = None, None
            if row["Low"] <= position["stop"]:
                exit_price, reason = position["stop"] * (1 - friction), "STOP"
            elif row["High"] >= position["target"]:
                exit_price, reason = position["target"] * (1 - friction), "TARGET"
            elif row["Close"] < row["EMA30"]:
                exit_price, reason = float(row["Close"]) * (1 - friction), "EMA30 EXIT"
            if exit_price is not None:
                pnl = (exit_price - position["entry"]) * position["quantity"]
                cash += pnl
                trades.append({**position, "exit_date": date, "exit": exit_price,
                               "reason": reason, "pnl": pnl,
                               "return_pct": (exit_price / position["entry"] - 1) * 100})
                position = None
        marked = cash if not position else cash + (float(row["Close"]) - position["entry"]) * position["quantity"]
        equity.append({"Date": date, "Equity": marked})
    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity).set_index("Date")
    if trades_df.empty:
        metrics = {"trades": 0, "win_rate": 0.0, "return_pct": 0.0, "net_profit": 0.0, "max_drawdown_pct": 0.0}
    else:
        dd = equity_df["Equity"] / equity_df["Equity"].cummax() - 1
        metrics = {"trades": len(trades_df), "win_rate": float((trades_df["pnl"] > 0).mean() * 100),
                   "return_pct": float((cash / cfg.capital - 1) * 100), "net_profit": float(cash - cfg.capital),
                   "max_drawdown_pct": float(dd.min() * 100)}
    return trades_df, equity_df, metrics
