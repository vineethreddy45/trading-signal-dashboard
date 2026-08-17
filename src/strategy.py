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

    rule_map = {
        "Weekly": "W-FRI",
        "Monthly": "ME",
        "Quarterly": "QE",
    }
    rule = rule_map.get(timeframe, "W-FRI")

    return daily.resample(rule).agg(
        Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
        Close=("Close", "last"), Volume=("Volume", "sum")
    ).dropna()


def enrich(data: pd.DataFrame, cfg: StrategyConfig) -> pd.DataFrame:
    df = data.copy()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA30"] = df["Close"].ewm(span=30, adjust=False).mean()
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()
    df["SUPPORT20"] = df["Low"].rolling(20).min().shift(1)
    df["RESISTANCE20"] = df["High"].rolling(20).max().shift(1)
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
            (df["EMA20_RISING"] & df["EMA30_RISING"]) &
            (df["Close"] > df["PRIOR_HIGH"])
        )
        df["PULLBACK_BUY"] = (
            (df["ABOVE_EMA30"] | df["ABOVE_EMA20"]) & df["EMA_STACK"] &
            (df["Low"] <= df["EMA20"]) & (df["Close"] > df["EMA20"]) &
            df["EMA20_RISING"]
        )
    else:
        df["BREAKOUT_BUY"] = (
            df["ABOVE_EMA20"] & df["ABOVE_EMA30"] & df["EMA_STACK"] &
            df["EMA20_RISING"] & df["EMA30_RISING"] &
            (df["Close"] > df["PRIOR_HIGH"])
        )
        df["PULLBACK_BUY"] = (
            df["ABOVE_EMA30"] & df["EMA_STACK"] & (df["Low"] <= df["EMA20"]) &
            (df["Close"] > df["EMA20"]) & df["EMA20_RISING"]
        )

    candle_range = (df["High"] - df["Low"]).replace(0, np.nan)
    body_size = (df["Close"] - df["Open"]).abs()
    upper_wick = (df["High"] - df[["Open", "Close"]].max(axis=1)).clip(lower=0)
    lower_wick = (df[["Open", "Close"]].min(axis=1) - df["Low"]).clip(lower=0)

    df["IS_DOJI"] = (body_size / candle_range) <= 0.15
    df["LOWER_WICK_PCT"] = lower_wick / candle_range
    df["UPPER_WICK_PCT"] = upper_wick / candle_range

    support_base = df["SUPPORT20"].replace(0, np.nan)
    resistance_base = df["RESISTANCE20"].replace(0, np.nan)
    df["NEAR_SUPPORT"] = (df["Low"] / support_base) <= 1.01
    df["NEAR_RESISTANCE"] = (df["High"] / resistance_base) >= 0.99

    df["DOUBLE_DOJI"] = df["IS_DOJI"] & df["IS_DOJI"].shift(1, fill_value=False)
    support_zone = df["NEAR_SUPPORT"] | df["NEAR_SUPPORT"].shift(1, fill_value=False)
    resistance_zone = df["NEAR_RESISTANCE"] | df["NEAR_RESISTANCE"].shift(1, fill_value=False)

    lower_wick_pair = (df["LOWER_WICK_PCT"] >= 0.35) | (df["LOWER_WICK_PCT"].shift(1, fill_value=0) >= 0.35)
    upper_wick_pair = (df["UPPER_WICK_PCT"] >= 0.35) | (df["UPPER_WICK_PCT"].shift(1, fill_value=0) >= 0.35)

    prev_body_high = df[["Open", "Close"]].shift(1).max(axis=1)
    prev_body_low = df[["Open", "Close"]].shift(1).min(axis=1)

    df["DOUBLE_DOJI_SUPPORT_BUY"] = (
        df["DOUBLE_DOJI"]
        & support_zone
        & lower_wick_pair
        & (df["Close"] >= prev_body_high)
        & df["ABOVE_EMA30"]
    )
    df["DOUBLE_DOJI_RESISTANCE_ALERT"] = (
        df["DOUBLE_DOJI"]
        & resistance_zone
        & upper_wick_pair
        & (df["Close"] <= prev_body_low)
    )

    score = (df["ABOVE_EMA20"].astype(int) + df["ABOVE_EMA30"].astype(int) +
             df["EMA_STACK"].astype(int) + df["EMA20_RISING"].astype(int) +
             df["EMA30_RISING"].astype(int))
    df["SIGNAL"] = np.select(
        [
            df["BREAKOUT_BUY"],
            df["DOUBLE_DOJI_SUPPORT_BUY"],
            df["PULLBACK_BUY"],
            df["DOUBLE_DOJI_RESISTANCE_ALERT"],
            score >= 5,
            score >= 3,
        ],
        [
            "BREAKOUT BUY",
            "DOUBLE DOJI SUPPORT BUY",
            "PULLBACK BUY",
            "DOUBLE DOJI RESISTANCE ALERT",
            "WATCH",
            "NEUTRAL",
        ],
        default="AVOID",
    )
    return df


def latest_signal_row(data: pd.DataFrame) -> pd.Series:
    if data.empty:
        raise ValueError("No data available to resolve the latest signal.")

    valid = data[data[["EMA20", "EMA30"]].notna().all(axis=1)].copy()
    if valid.empty:
        valid = data.copy()

    ordered = valid.sort_index()
    latest_idx = ordered.index.max()
    latest = ordered.loc[[latest_idx]]
    return latest.iloc[0]


def latest_signal(data: pd.DataFrame, cfg: StrategyConfig) -> dict:
    df = enrich(data, cfg)
    row = latest_signal_row(df)
    bar_date = row.name.date() if hasattr(row.name, "date") else pd.Timestamp(row.name).date()

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
    commission_rate = cfg.commission_pct / 100
    slippage_rate = cfg.slippage_pct / 100
    total_costs = 0.0
    for i in range(1, len(df)):
        date, row, prev = df.index[i], df.iloc[i], df.iloc[i-1]
        if position is None and bool(prev["BREAKOUT_BUY"]):
            entry, stop = float(row["Open"]) * (1 + slippage_rate), float(prev["STOP"])
            if np.isfinite(stop) and 0 < stop < entry:
                risk_per_share = entry - stop
                qty = min(int((cash * cfg.risk_pct / 100) // risk_per_share), int(cash // entry))
                if qty > 0:
                    entry_commission = entry * qty * commission_rate
                    cash -= entry_commission
                    total_costs += entry_commission
                    position = {"entry_date": date, "entry": entry, "stop": stop,
                                "target": entry + cfg.target_r * risk_per_share, "quantity": qty,
                                "entry_commission": entry_commission}
        if position:
            exit_price, reason = None, None
            if row["Low"] <= position["stop"]:
                exit_price, reason = position["stop"] * (1 - slippage_rate), "STOP"
            elif row["High"] >= position["target"]:
                exit_price, reason = position["target"] * (1 - slippage_rate), "TARGET"
            elif row["Close"] < row["EMA30"]:
                exit_price, reason = float(row["Close"]) * (1 - slippage_rate), "EMA30 EXIT"
            if exit_price is not None:
                exit_commission = exit_price * position["quantity"] * commission_rate
                gross_pnl = (exit_price - position["entry"]) * position["quantity"]
                costs = float(position["entry_commission"]) + exit_commission
                net_pnl = gross_pnl - exit_commission
                cash += net_pnl
                total_costs += exit_commission
                trades.append({**position, "exit_date": date, "exit": exit_price,
                               "reason": reason, "gross_pnl": gross_pnl, "costs": costs,
                               "pnl": net_pnl,
                               "return_pct": (exit_price / position["entry"] - 1) * 100})
                position = None
        marked = cash if not position else cash + (float(row["Close"]) - position["entry"]) * position["quantity"]
        equity.append({"Date": date, "Equity": marked})
    trades_df = pd.DataFrame(trades)
    equity_df = pd.DataFrame(equity).set_index("Date")
    if trades_df.empty:
        metrics = {
            "trades": 0,
            "win_rate": 0.0,
            "return_pct": 0.0,
            "net_profit": 0.0,
            "max_drawdown_pct": 0.0,
            "total_costs": 0.0,
        }
    else:
        dd = equity_df["Equity"] / equity_df["Equity"].cummax() - 1
        metrics = {
            "trades": len(trades_df),
            "win_rate": float((trades_df["pnl"] > 0).mean() * 100),
            "return_pct": float((cash / cfg.capital - 1) * 100),
            "net_profit": float(cash - cfg.capital),
            "max_drawdown_pct": float(dd.min() * 100),
            "total_costs": float(total_costs),
        }
    return trades_df, equity_df, metrics
