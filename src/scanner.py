from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from src.market_data import download_history
from src.strategy import StrategyConfig, convert_timeframe, latest_signal


def scan_symbols(symbols_df: pd.DataFrame, timeframe: str, limit: int | None = None) -> pd.DataFrame:
    rows, source = [], symbols_df.head(limit) if limit else symbols_df
    cfg = StrategyConfig(timeframe=timeframe)
    for item in source.itertuples(index=False):
        try:
            daily = download_history(item.symbol, "3y")
            signal = latest_signal(convert_timeframe(daily, timeframe), cfg)
            rows.append({"Symbol": item.display_symbol, "Market": item.market,
                         "Signal": signal["signal"], "Close": signal["close"],
                         "EMA20": signal["ema20"], "EMA30": signal["ema30"],
                         "Volume Confirm": signal["volume_confirm"], "Close > EMA20": signal["above_ema20"],
                         "Close > EMA30": signal["above_ema30"], "EMA20 > EMA30": signal["ema_stack"],
                         "Bar Date": signal["bar_date"]})
        except Exception as exc:
            rows.append({"Symbol": item.display_symbol, "Market": item.market,
                         "Signal": "ERROR", "Error": str(exc)})
    result = pd.DataFrame(rows)
    order = {"BREAKOUT BUY":1,"PULLBACK BUY":2,"WATCH":3,"NEUTRAL":4,"AVOID":5,"ERROR":9}
    result["_rank"] = result["Signal"].map(order).fillna(99)
    return result.sort_values(["_rank","Market","Symbol"]).drop(columns="_rank")
