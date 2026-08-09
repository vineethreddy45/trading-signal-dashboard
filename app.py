from pathlib import Path
import html as html_lib
import logging
import re
import resource
import sys
from urllib.parse import quote_plus
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from src.market_data import download_history, latest_price
from src.scanner import scan_symbols
from src.strategy import StrategyConfig, backtest, convert_timeframe, enrich, latest_signal
from src.watchlist_store import (
    add_symbols_to_watchlist,
    create_watchlist,
    delete_watchlist,
    list_watchlist_names,
    load_watchlists,
    remove_symbol_from_watchlist,
    save_watchlists,
)

st.set_page_config(page_title="Trading Signal Dashboard", layout="wide")

logger = logging.getLogger("trading_dashboard")


def process_memory_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


def log_runtime_event(event: str):
    logger.info("%s | memory_mb=%.1f", event, process_memory_mb())


def detect_assistant_intent(query: str) -> str:
    q = str(query).strip().lower()
    if not q:
        return "help"

    if any(token in q for token in ["compare", "vs", "versus"]):
        return "symbol_compare"
    if any(token in q for token in ["risk", "drawdown", "exposure", "danger"]):
        return "risk_summary"
    if "watchlist" in q:
        return "watchlist_summary"
    if "top" in q and any(token in q for token in ["scanner", "setup", "symbol", "symbols"]):
        return "top_setups"
    if any(token in q for token in ["signal", "current"]):
        return "current_signal"
    if any(token in q for token in ["backtest", "return", "win rate", "performance"]):
        return "backtest_summary"
    return "help"


def extract_symbols_from_query(query: str) -> list[str]:
    raw = re.findall(r"\b[A-Za-z]{1,6}(?:\.[A-Za-z]{1,3})?\b", str(query))
    symbols: list[str] = []
    for token in raw:
        up = token.upper()
        if up in {"TOP", "SETUP", "SETUPS", "WATCHLIST", "SIGNAL", "RISK", "RETURN", "COMPARE", "VERSUS"}:
            continue
        if any(ch.isdigit() for ch in up):
            continue
        symbols.append(up)
    # Keep order while deduplicating.
    return list(dict.fromkeys(symbols))


def _build_symbol_lookup(scanner_df: pd.DataFrame, watchlist_df: pd.DataFrame) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for df in [scanner_df, watchlist_df]:
        if df.empty or "Quote Symbol" not in df.columns:
            continue
        for _, row in df.iterrows():
            sym = str(row.get("Quote Symbol") or "").strip().upper()
            if not sym:
                continue
            lookup[sym] = {
                "Signal": str(row.get("Signal") or "Unknown"),
                "Setup Score": float(pd.to_numeric(row.get("Setup Score"), errors="coerce") or 0.0),
                "Sector": str(row.get("Sector") or "Unknown"),
                "Industry": str(row.get("Industry") or "Unknown"),
                "Market": str(row.get("Market") or "Unknown"),
                "Bar Date": str(row.get("Bar Date") or ""),
            }
    return lookup


def build_assistant_reply(
    query: str,
    scanner_df: pd.DataFrame,
    watchlist_df: pd.DataFrame,
    current_signal: dict,
    metrics: dict,
) -> str:
    intent = detect_assistant_intent(query)
    q = str(query).strip()

    if intent == "top_setups":
        if scanner_df.empty:
            return "Intent: top_setups\nSummary: scanner results are empty.\nAction: run scanner first, then ask for top setups."
        top = scanner_df.sort_values("Setup Score", ascending=False).head(5)
        rows = [
            f"{r['Quote Symbol']} ({r['Signal']}) score {float(r.get('Setup Score', 0.0)):.1f}"
            for _, r in top.iterrows()
        ]
        return "Intent: top_setups\nSummary: top scanner setups by score.\nEvidence:\n" + "\n".join(rows)

    if intent == "watchlist_summary":
        if watchlist_df.empty:
            return "Intent: watchlist_summary\nSummary: selected watchlist is empty.\nAction: add symbols from scanner results."
        sector_count = watchlist_df["Sector"].fillna("Unknown").value_counts().head(3)
        sector_text = ", ".join([f"{name} ({count})" for name, count in sector_count.items()])
        avg_score = pd.to_numeric(watchlist_df.get("Setup Score"), errors="coerce").fillna(0.0).mean()
        return (
            "Intent: watchlist_summary\n"
            f"Summary: watchlist has {len(watchlist_df)} symbols with average score {avg_score:.1f}.\n"
            f"Evidence: top sectors are {sector_text}."
        )

    if intent == "current_signal":
        return (
            "Intent: current_signal\n"
            f"Summary: current chart signal is {current_signal['signal']}.\n"
            f"Evidence: close={current_signal['close']:.2f}, EMA20={current_signal['ema20']:.2f}, "
            f"EMA30={current_signal['ema30']:.2f}, volume_confirm={current_signal['volume_confirm']}."
        )

    if intent == "backtest_summary":
        return (
            "Intent: backtest_summary\n"
            f"Summary: return={metrics['return_pct']:.1f}% with win rate={metrics['win_rate']:.1f}%.\n"
            f"Evidence: trades={metrics['trades']}, max_drawdown={metrics['max_drawdown_pct']:.1f}%, "
            f"transaction_costs={metrics.get('total_costs', 0.0):,.2f}."
        )

    if intent == "symbol_compare":
        lookup = _build_symbol_lookup(scanner_df, watchlist_df)
        symbols = extract_symbols_from_query(q)
        if len(symbols) < 2 and not scanner_df.empty and "Quote Symbol" in scanner_df.columns:
            top_two = scanner_df.sort_values("Setup Score", ascending=False)["Quote Symbol"].astype(str).head(2).tolist()
            symbols = list(dict.fromkeys(symbols + [s.upper() for s in top_two]))

        if len(symbols) < 2:
            return "Intent: symbol_compare\nSummary: need two symbols to compare.\nAction: ask like 'compare NVDA vs AAPL'."

        a, b = symbols[0], symbols[1]
        if a not in lookup or b not in lookup:
            missing = [s for s in [a, b] if s not in lookup]
            return (
                "Intent: symbol_compare\n"
                f"Summary: cannot compare {a} vs {b} because missing context for {', '.join(missing)}.\n"
                "Action: run scanner or add symbols to watchlist first."
            )

        left, right = lookup[a], lookup[b]
        better = a if left["Setup Score"] >= right["Setup Score"] else b
        return (
            "Intent: symbol_compare\n"
            f"Summary: {better} currently has stronger setup score.\n"
            f"Evidence: {a} -> signal={left['Signal']}, score={left['Setup Score']:.1f}, sector={left['Sector']}; "
            f"{b} -> signal={right['Signal']}, score={right['Setup Score']:.1f}, sector={right['Sector']}."
        )

    if intent == "risk_summary":
        if watchlist_df.empty:
            concentration_text = "watchlist is empty"
        else:
            sector_share = watchlist_df["Sector"].fillna("Unknown").value_counts(normalize=True)
            top_sector = sector_share.index[0]
            top_sector_pct = float(sector_share.iloc[0] * 100)
            concentration_text = f"top sector {top_sector} at {top_sector_pct:.1f}%"

        return (
            "Intent: risk_summary\n"
            f"Summary: drawdown={metrics['max_drawdown_pct']:.1f}% and {concentration_text}.\n"
            f"Evidence: trades={metrics['trades']}, win_rate={metrics['win_rate']:.1f}%, "
            f"return={metrics['return_pct']:.1f}%, transaction_costs={metrics.get('total_costs', 0.0):,.2f}."
        )

    return (
        "Intent: help\n"
        "Try one of these prompts:\n"
        "- top 5 scanner setups\n"
        "- watchlist summary\n"
        "- current signal\n"
        "- backtest return\n"
        "- compare NVDA vs AAPL\n"
        "- risk summary"
    )

st.markdown(
    """
    <style>
    html, body, [data-testid="stAppViewContainer"], [data-testid="stMain"], .stApp {
        background: linear-gradient(180deg, #07111f 0%, #0f172a 100%);
        color: #e8edf8 !important;
    }
    .stApp .main .block-container {
        padding-top: 1.2rem;
        padding-bottom: 2rem;
        max-width: 1500px;
    }
    p, li, div, span, label, h1, h2, h3, h4, h5, h6 {
        color: #e8edf8 !important;
    }
    [data-testid="stSidebar"] {
        background: rgba(15, 23, 42, 0.96);
        border-right: 1px solid rgba(148, 163, 184, 0.2);
    }
    [data-testid="stSidebar"] * {
        color: #ecf4ff !important;
    }
    [data-testid="stMetric"] {
        background: rgba(15, 23, 42, 0.85);
        border: 1px solid rgba(148, 163, 184, 0.22);
        border-radius: 14px;
        padding: 0.85rem 0.95rem;
        box-shadow: 0 8px 18px rgba(15, 23, 42, 0.22);
    }
    [data-testid="stMetric"] > div {
        color: #e8edf8 !important;
    }
    .stTabs [role="tablist"] {
        gap: 0.5rem;
    }
    .stTabs [role="tab"] {
        background: rgba(15, 23, 42, 0.9);
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 0.7rem 0.7rem 0 0;
        color: #dfe9f6;
        padding: 0.5rem 1rem;
    }
    .stTabs [role="tab"][aria-selected="true"] {
        background: linear-gradient(135deg, #2563eb, #22c55e);
        color: white;
        font-weight: 600;
    }
    .stDataFrame, .stTable, .stJson, .stCodeBlock {
        background: rgba(15, 23, 42, 0.7);
        border-radius: 12px;
        overflow: hidden;
    }
    .stDataFrame table, .stDataFrame th, .stDataFrame td {
        color: #e8edf8 !important;
        background-color: rgba(15, 23, 42, 0.65) !important;
    }
    .cap-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.02em;
        color: white !important;
        background: linear-gradient(135deg, #2563eb, #7c3aed);
        border: 1px solid rgba(255,255,255,0.15);
    }
    .cap-badge.mega { background: linear-gradient(135deg, #7c3aed, #2563eb); }
    .cap-badge.large { background: linear-gradient(135deg, #0ea5e9, #2563eb); }
    .cap-badge.mid { background: linear-gradient(135deg, #22c55e, #16a34a); }
    .cap-badge.small { background: linear-gradient(135deg, #f59e0b, #ef4444); }
    .hero-card {
        background: linear-gradient(135deg, rgba(15,23,42,0.86), rgba(30,41,59,0.75));
        border: 1px solid rgba(148,163,184,0.18);
        border-radius: 18px;
        padding: 1rem 1.2rem;
        margin-bottom: 1rem;
        box-shadow: 0 12px 24px rgba(15, 23, 42, 0.22);
    }
    .hero-label {
        font-size: 0.72rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #a5b4cf !important;
        margin-bottom: 0.7rem;
    }
    .hero-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 0.8rem;
    }
    .hero-item {
        background: rgba(15, 23, 42, 0.6);
        border: 1px solid rgba(148,163,184,0.16);
        border-radius: 12px;
        padding: 0.75rem 0.9rem;
    }
    .hero-item .key {
        display: block;
        color: #9fb5d6 !important;
        font-size: 0.72rem;
        margin-bottom: 0.25rem;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .hero-item strong { font-size: 1.05rem; color: white !important; }
    .signal-pill {
        display: inline-block;
        padding: 5px 12px;
        border-radius: 999px;
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.04em;
        color: white !important;
        border: 1px solid rgba(255,255,255,0.18);
    }
    .signal-pill.breakout { background: linear-gradient(135deg, #16a34a, #22c55e); }
    .signal-pill.pullback { background: linear-gradient(135deg, #0ea5e9, #2563eb); }
    .signal-pill.doji_support { background: linear-gradient(135deg, #22c55e, #0ea5e9); }
    .signal-pill.doji_resistance { background: linear-gradient(135deg, #f97316, #dc2626); }
    .signal-pill.watch { background: linear-gradient(135deg, #f59e0b, #f97316); }
    .signal-pill.neutral { background: linear-gradient(135deg, #94a3b8, #64748b); }
    .signal-pill.avoid { background: linear-gradient(135deg, #ef4444, #b91c1c); }
    .signal-pill.error { background: linear-gradient(135deg, #f43f5e, #9f1239); }
    [data-testid="stBaseButton-secondary"], button, .stDownloadButton button {
        color: #e8edf8 !important;
    }
    .stTextInput input, .stSelectbox div[data-baseweb="select"] > div, .stNumberInput input, .stRadio > div, .stMultiSelect div {
        background: #0f172a !important;
        color: #e8edf8 !important;
        border: 1px solid rgba(148, 163, 184, 0.35) !important;
    }
    [role="radio"][aria-checked="true"], [role="option"][aria-selected="true"], [aria-selected="true"], [data-baseweb="select"] [aria-selected="true"] {
        background: transparent !important;
        color: #e8edf8 !important;
        box-shadow: none !important;
        border-color: rgba(148, 163, 184, 0.35) !important;
    }
    [data-baseweb="popover"], [role="listbox"], [role="option"], [data-baseweb="menu"], ul[role="listbox"] {
        background: #0f172a !important;
        color: #e8edf8 !important;
        border: 1px solid rgba(148, 163, 184, 0.35) !important;
    }
    [role="option"] > div, [role="option"] {
        background: #0f172a !important;
        color: #e8edf8 !important;
    }
    .stTextInput label, .stSelectbox label, .stNumberInput label, .stCheckbox label, .stRadio label, .stMultiSelect label {
        color: #e8edf8 !important;
        font-weight: 500;
    }
    .stAlert, .stWarning, .stError, .stInfo {
        border-radius: 12px;
    }
    .strategy-panel {
        background: rgba(226, 232, 240, 0.12);
        border: 1px solid rgba(148, 163, 184, 0.28);
        border-radius: 12px;
        padding: 0.65rem 0.75rem 0.35rem 0.75rem;
        margin: 0.35rem 0 0.5rem 0;
    }
    .strategy-panel-title {
        font-size: 1rem;
        font-weight: 700;
        margin-bottom: 0.15rem;
    }
    .strategy-panel-hint {
        color: #cbd5e1 !important;
        font-size: 0.78rem;
        margin-bottom: 0.15rem;
    }
    .strategy-divider {
        height: 1px;
        background: rgba(148, 163, 184, 0.25);
        margin: 0.35rem 0 0.5rem 0;
    }
    .stNumberInput [data-testid="stNumberInputContainer"] {
        border-radius: 10px;
    }
    .stNumberInput button {
        border-radius: 8px !important;
        min-width: 1.8rem;
        height: 1.8rem;
    }
    .stDataFrame td, .stDataFrame th {
        background: rgba(15, 23, 42, 0.95) !important;
        color: #e8edf8 !important;
    }
    .stCheckbox > label > span {
        color: #e8edf8 !important;
    }
    [data-testid="stSidebar"] .stSelectbox [data-baseweb="select"] > div,
    [data-testid="stSidebar"] .stSelectbox [role="listbox"],
    [data-testid="stSidebar"] .stSelectbox [role="option"] {
        background: #0f172a !important;
        color: #e8edf8 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("📈 Trading Signal Dashboard")
st.caption("Daily and weekly swing trade ideas with a cleaner scanner workflow.")
log_runtime_event("app_render_start")

# Map UI market names to CSV market values
MARKET_LABELS = {"India": "India", "US": "USA"}

signal_style = {
    "BREAKOUT BUY": "breakout",
    "PULLBACK BUY": "pullback",
    "DOUBLE DOJI SUPPORT BUY": "doji_support",
    "DOUBLE DOJI RESISTANCE ALERT": "doji_resistance",
    "WATCH": "watch",
    "NEUTRAL": "neutral",
    "AVOID": "avoid",
    "ERROR": "error",
}
MARKET_CAP_OPTIONS = ["All", "Mega Cap", "Large Cap", "Mid Cap"]
MARKET_CAP_HELP = {
    "Mega Cap": "$200B+",
    "Large Cap": "$10B to $200B",
    "Mid Cap": "$2B to $10B",
}


@st.cache_data(ttl=3600)
def load_symbols():
    return pd.read_csv(Path("data/symbols.csv"))


@st.cache_data(ttl=3600, show_spinner=False)
def load_history(symbol, period):
    return download_history(symbol, period)


@st.cache_data(ttl=86400, show_spinner=False)
def company_name_from_ticker(ticker: str) -> str:
    ticker = str(ticker).strip()
    if not ticker:
        return ticker
    try:
        return yf.Ticker(ticker).info.get("shortName") or ticker
    except Exception:
        return ticker


@st.cache_data(ttl=1800, show_spinner=False)
def search_yahoo_symbols(query: str, market_label: str, max_results: int = 12) -> pd.DataFrame:
    cols = ["symbol", "name", "exchange"]
    q = str(query).strip()
    if not q:
        return pd.DataFrame(columns=cols)

    try:
        search = yf.Search(q, max_results=max_results, news_count=0)
        quotes = getattr(search, "quotes", []) or []
    except Exception:
        return pd.DataFrame(columns=cols)

    rows = []
    for item in quotes:
        symbol = str(item.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        exchange = str(item.get("exchDisp") or item.get("exchange") or "").strip()
        name = str(item.get("shortname") or item.get("longname") or symbol).strip()
        quote_type = str(item.get("quoteType") or "").upper()
        if quote_type and quote_type not in {"EQUITY", "ETF"}:
            continue

        if market_label == "US" and (symbol.endswith(".NS") or symbol.endswith(".BO")):
            continue
        if market_label == "India":
            exchange_upper = exchange.upper()
            is_india_symbol = symbol.endswith(".NS") or symbol.endswith(".BO")
            is_india_exchange = ("NSE" in exchange_upper) or ("BSE" in exchange_upper) or (exchange_upper in {"NSI", "BOM"})
            if not (is_india_symbol or is_india_exchange):
                continue

        rows.append({"symbol": symbol, "name": name, "exchange": exchange})

    if not rows:
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame(rows).drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    return out[cols]


def quote_symbol_for_row(row: pd.Series) -> str:
    direct = str(row.get("Quote Symbol", "")).strip().upper()
    if direct:
        return direct
    symbol = str(row.get("Symbol", "")).strip().upper()
    market = str(row.get("Market", "")).strip().upper()
    if market == "INDIA" and symbol and "." not in symbol:
        return f"{symbol}.NS"
    return symbol


@st.cache_data(ttl=900, show_spinner=False)
def run_scanner_cached(
    symbols_df: pd.DataFrame,
    timeframe: str,
    count: int,
    fast_ema: int,
    slow_ema: int,
    require_price_above_ema200: bool,
) -> pd.DataFrame:
    return scan_symbols(
        symbols_df,
        timeframe,
        count,
        fast_ema=fast_ema,
        slow_ema=slow_ema,
        require_price_above_ema200=require_price_above_ema200,
    )


def apply_symbol_from_query(symbols_df: pd.DataFrame) -> None:
    query_symbol = st.query_params.get("symbol")
    if not query_symbol:
        return

    symbol = str(query_symbol).strip().upper()
    match = symbols_df[symbols_df["symbol"].astype(str).str.upper() == symbol]
    if match.empty:
        st.query_params.clear()
        return

    st.session_state["selected_symbol"] = symbol
    market_value = str(match.iloc[0]["market"])
    for label, value in MARKET_LABELS.items():
        if value == market_value:
            st.session_state["market_selector"] = label
            break
    st.query_params.clear()


def render_scanner_table(rows: pd.DataFrame, selected_market: str) -> None:
    table = [
        '<table style="width:100%; border-collapse:collapse;">',
        (
            "<thead><tr>"
            "<th style='text-align:left;padding:8px;'>Company Name</th>"
            "<th style='text-align:left;padding:8px;'>Ticker</th>"
            "<th style='text-align:left;padding:8px;'>Market</th>"
            "<th style='text-align:left;padding:8px;'>Sector</th>"
            "<th style='text-align:left;padding:8px;'>Industry</th>"
            "<th style='text-align:left;padding:8px;'>Market Cap</th>"
            "<th style='text-align:left;padding:8px;'>Cap Tier</th>"
            "<th style='text-align:left;padding:8px;'>Signal</th>"
            "<th style='text-align:left;padding:8px;'>Setup Score</th>"
            "<th style='text-align:left;padding:8px;'>Trend</th>"
            "<th style='text-align:left;padding:8px;'>Vol Ratio</th>"
            "<th style='text-align:left;padding:8px;'>Bar Date</th>"
            "<th style='text-align:left;padding:8px;'>Yahoo</th>"
            "<th style='text-align:left;padding:8px;'>TradingView</th>"
            "</tr></thead><tbody>"
        ),
    ]

    for _, row in rows.iterrows():
        ticker = str(row["Ticker"]).strip()
        name = html_lib.escape(str(row["Company Name"]))
        market = html_lib.escape(str(row["Market"]))
        sector = html_lib.escape(str(row.get("Sector", "Unknown")))
        industry = html_lib.escape(str(row.get("Industry", "Unknown")))
        market_cap = html_lib.escape(str(row["Market Cap"]))
        cap_tier = html_lib.escape(str(row["Cap Tier"]))
        signal = html_lib.escape(str(row["Signal"]))
        setup_score = float(row.get("Setup Score", 0.0) or 0.0)
        trend_score = float(row.get("Trend Score", 0.0) or 0.0)
        volume_ratio = float(row.get("Volume Ratio", 0.0) or 0.0)
        bar_date = html_lib.escape(str(row["Bar Date"]))
        symbol_link = f"?symbol={quote_plus(ticker)}&market={quote_plus(selected_market)}"
        yahoo_link = html_lib.escape(str(row["Yahoo"]))
        tradingview_link = html_lib.escape(str(row["TradingView"]))

        table.append(
            (
                "<tr>"
                f"<td style='padding:8px;'><a href='{symbol_link}' target='_self'>{name}</a></td>"
                f"<td style='padding:8px;'>{html_lib.escape(ticker)}</td>"
                f"<td style='padding:8px;'>{market}</td>"
                f"<td style='padding:8px;'>{sector}</td>"
                f"<td style='padding:8px;'>{industry}</td>"
                f"<td style='padding:8px;'>{market_cap}</td>"
                f"<td style='padding:8px;'>{cap_tier}</td>"
                f"<td style='padding:8px;'>{signal}</td>"
                f"<td style='padding:8px;'>{setup_score:.1f}</td>"
                f"<td style='padding:8px;'>{trend_score:.0f}/5</td>"
                f"<td style='padding:8px;'>{volume_ratio:.2f}x</td>"
                f"<td style='padding:8px;'>{bar_date}</td>"
                f"<td style='padding:8px;'><a href='{yahoo_link}' target='_blank' rel='noopener noreferrer'>Open</a></td>"
                f"<td style='padding:8px;'><a href='{tradingview_link}' target='_blank' rel='noopener noreferrer'>Chart</a></td>"
                "</tr>"
            )
        )

    table.append("</tbody></table>")
    st.markdown("".join(table), unsafe_allow_html=True)


def setup_score_band(score: float) -> tuple[str, str]:
    if score >= 80:
        return "High", "#22c55e"
    if score >= 60:
        return "Medium", "#0ea5e9"
    return "Low", "#f59e0b"


def render_scanner_cards(rows: pd.DataFrame, selected_market: str, limit: int = 12) -> None:
    if rows.empty:
        st.info("No results to show in card view.")
        return

    data = rows.head(limit).reset_index(drop=True)
    cols = st.columns(2)
    for idx, row in data.iterrows():
        col = cols[idx % 2]
        ticker = str(row.get("Ticker") or row.get("Quote Symbol") or "").strip()
        company = html_lib.escape(str(row.get("Company Name") or ticker))
        signal = str(row.get("Signal") or "Unknown")
        score = float(row.get("Setup Score") or 0.0)
        score_band, score_color = setup_score_band(score)
        sector = html_lib.escape(str(row.get("Sector") or "Unknown"))
        industry = html_lib.escape(str(row.get("Industry") or "Unknown"))
        symbol_link = f"?symbol={quote_plus(ticker)}&market={quote_plus(selected_market)}"
        yahoo_link = html_lib.escape(str(row.get("Yahoo") or ""))

        with col:
            st.markdown(
                (
                    "<div style='background:rgba(15,23,42,0.72);border:1px solid rgba(148,163,184,0.18);"
                    "border-radius:14px;padding:0.85rem;margin-bottom:0.75rem;'>"
                    f"<div style='display:flex;justify-content:space-between;gap:0.5rem;align-items:center;'>"
                    f"<a href='{symbol_link}' target='_self' style='color:#e8edf8;text-decoration:none;font-weight:700;'>{company}</a>"
                    f"<span style='font-size:0.72rem;padding:3px 8px;border-radius:999px;background:{score_color};color:white;'>{score_band}</span>"
                    "</div>"
                    f"<div style='margin-top:0.35rem;font-size:0.82rem;color:#cbd5e1;'>"
                    f"{html_lib.escape(ticker)} • {html_lib.escape(str(row.get('Market') or 'Unknown'))}</div>"
                    f"<div style='margin-top:0.35rem;'><span class='signal-pill {signal_style.get(signal, 'neutral')}'>{html_lib.escape(signal)}</span></div>"
                    f"<div style='margin-top:0.5rem;font-size:0.8rem;color:#cbd5e1;'>Score {score:.1f} • Sector: {sector} • Industry: {industry}</div>"
                    f"<div style='margin-top:0.45rem;font-size:0.78rem;'><a href='{yahoo_link}' target='_blank' rel='noopener noreferrer'"
                    " style='color:#93c5fd;text-decoration:none;'>Open on Yahoo</a></div>"
                    "</div>"
                ),
                unsafe_allow_html=True,
            )


def build_signal_explanation(row: pd.Series) -> pd.DataFrame:
    checks = [
        ("Signal", str(row.get("Signal", "Unknown"))),
        ("Setup Score", f"{float(row.get('Setup Score', 0.0) or 0.0):.1f}"),
        ("Close > EMA20", bool(row.get("Close > EMA20", False))),
        ("Close > EMA30", bool(row.get("Close > EMA30", False))),
        ("Close > EMA200", bool(row.get("Close > EMA200", False))),
        ("EMA20 > EMA30", bool(row.get("EMA20 > EMA30", False))),
        ("Volume Confirm", bool(row.get("Volume Confirm", False))),
        ("Trend Score", f"{float(row.get('Trend Score', 0.0) or 0.0):.1f}/5"),
        ("Volume Ratio", f"{float(row.get('Volume Ratio', 0.0) or 0.0):.2f}x"),
        ("Distance to EMA20 %", f"{float(row.get('Distance to EMA20 %', 0.0) or 0.0):.2f}%"),
        ("Sector", str(row.get("Sector", "Unknown"))),
        ("Industry", str(row.get("Industry", "Unknown"))),
        ("Bar Date", str(row.get("Bar Date", ""))),
    ]
    return pd.DataFrame(checks, columns=["Condition", "Value"])


symbols = load_symbols()
if "_defaults_initialized" not in st.session_state:
    st.session_state["market_selector"] = None
    st.session_state["timeframe_selector"] = None
    st.session_state["_defaults_initialized"] = True
if "watchlists" not in st.session_state:
    st.session_state["watchlists"] = load_watchlists()
if "watchlist_active_name" not in st.session_state:
    names = list_watchlist_names(st.session_state["watchlists"])
    st.session_state["watchlist_active_name"] = names[0] if names else "Default"
apply_symbol_from_query(symbols)

with st.sidebar:
    st.header("Quick setup")
    market = st.selectbox(
        "Market",
        list(MARKET_LABELS.keys()),
        key="market_selector",
        index=None,
        placeholder="Select market",
    )

    symbol = None
    display = None
    search_query = st.text_input("Search symbol", value="")
    if market:
        market_value = MARKET_LABELS[market]
        market_df = symbols[symbols.market == market_value]

        if search_query:
            filtered_df = market_df[
                market_df["display_symbol"].str.contains(search_query, case=False, na=False)
                | market_df["symbol"].str.contains(search_query, case=False, na=False)
            ]
        else:
            filtered_df = market_df

        if not filtered_df.empty:
            display_options = filtered_df.display_symbol.tolist()
            selected_symbol_state = st.session_state.get("selected_symbol")
            current_display = st.session_state.get("symbol_selector")

            # Initialize or repair symbol selection only when current value is missing/invalid.
            if (current_display not in display_options) and selected_symbol_state is not None:
                current_match = filtered_df[
                    filtered_df["symbol"].astype(str).str.upper() == str(selected_symbol_state).upper()
                ]
                if not current_match.empty:
                    st.session_state["symbol_selector"] = current_match.iloc[0]["display_symbol"]

            if st.session_state.get("symbol_selector") not in display_options:
                st.session_state["symbol_selector"] = display_options[0]

            display = st.selectbox(
                "Symbol",
                display_options,
                key="symbol_selector",
                placeholder="Select symbol",
            )
            if display:
                symbol = filtered_df.loc[filtered_df.display_symbol == display, "symbol"].iloc[0]
                st.session_state["selected_symbol"] = symbol
        elif search_query:
            yahoo_matches = search_yahoo_symbols(search_query, market)
            if yahoo_matches.empty:
                st.warning("No matching symbol found locally or on Yahoo.")
            else:
                yahoo_labels = (
                    yahoo_matches["symbol"].astype(str)
                    + " - "
                    + yahoo_matches["name"].astype(str)
                    + " ("
                    + yahoo_matches["exchange"].astype(str)
                    + ")"
                ).tolist()
                yahoo_pick = st.selectbox("Yahoo Symbol", yahoo_labels, key="yahoo_symbol_selector")
                yahoo_row = yahoo_matches.iloc[yahoo_labels.index(yahoo_pick)]
                symbol = str(yahoo_row["symbol"]).strip().upper()
                display = symbol
                st.session_state["selected_symbol"] = symbol
                st.caption("Using Yahoo fallback symbol from search.")
        else:
            st.warning("No matching symbol found. Try a different search term.")
    else:
        st.selectbox("Symbol", [], index=None, key="symbol_selector", placeholder="Select market first")

    timeframe = st.radio(
        "Timeframe",
        ["Daily", "Weekly", "Monthly", "Quarterly"],
        horizontal=True,
        index=None,
        key="timeframe_selector",
    )
    period = st.selectbox("History", ["1y", "3y", "5y", "max"], index=0)
    st.markdown(
        """
        <div class="strategy-panel">
            <div class="strategy-panel-title">Strategy</div>
            <div class="strategy-panel-hint">Tune EMA speed and long-term trend filter.</div>
            <div class="strategy-divider"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    strategy_col1, strategy_col2 = st.columns(2)
    fast_ema = int(strategy_col1.number_input("Fast EMA", min_value=2, max_value=200, value=20, step=1))
    slow_ema = int(strategy_col2.number_input("Slow EMA", min_value=3, max_value=300, value=50, step=1))
    require_price_above_ema200 = st.checkbox("Require price > EMA 200", value=True)
    capital = st.number_input("Capital", min_value=1000.0, value=1_000_000.0 if market=="India" else 10_000.0, step=1000.0)
    c1, c2 = st.columns(2)
    commission_pct = c1.number_input("Commission %", min_value=0.0, max_value=2.0, value=0.05, step=0.01)
    slippage_pct = c2.number_input("Slippage %", min_value=0.0, max_value=2.0, value=0.05, step=0.01)
    st.caption("Market cap guide: Mega Cap = $200B+, Large Cap = $10B-$200B, Mid Cap = $2B-$10B.")


if not market or not symbol or not timeframe:
    st.info("Select Market, Symbol, and Timeframe from the sidebar to load the dashboard.")
    st.stop()

if not display:
    display = str(symbol).strip().upper()

if slow_ema <= fast_ema:
    st.error("Slow EMA must be greater than Fast EMA.")
    st.stop()


cfg = StrategyConfig(
    timeframe=timeframe,
    capital=capital,
    commission_pct=float(commission_pct),
    slippage_pct=float(slippage_pct),
    market=MARKET_LABELS.get(market, "USA"),
    fast_ema=fast_ema,
    slow_ema=slow_ema,
    require_price_above_ema200=require_price_above_ema200,
)
try:
    daily = load_history(symbol, period)
    bars = convert_timeframe(daily, timeframe)
    chart_data = enrich(bars, cfg)
    signal = latest_signal(bars, cfg)
    trades, equity, metrics = backtest(bars, cfg)
except Exception as exc:
    st.error(str(exc))
    st.stop()


t1, t3, t4, t5, t6 = st.tabs(["Overview", "Backtest", "Signal Scanner", "Watchlist", "Assistant"])
with t1:
    try:
        live, quote_time = latest_price(symbol)
    except Exception:
        live, quote_time = None, "Unavailable"

    st.subheader(f"{display} • {market} market")
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="hero-label">Market Snapshot</div>
            <div class="hero-grid">
                <div class="hero-item"><span class="key">Symbol</span><strong><a href="https://finance.yahoo.com/quote/{symbol}" target="_blank" rel="noopener noreferrer" style="color:#e8edf8; text-decoration:none;">{display}</a></strong></div>
                <div class="hero-item"><span class="key">Market</span><strong>{market}</strong></div>
                <div class="hero-item"><span class="key">Timeframe</span><strong>{timeframe}</strong></div>
                <div class="hero-item"><span class="key">Signal</span><strong><span class="signal-pill {signal_style.get(signal['signal'], 'neutral')}">{signal['signal']}</span></strong></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    overview = st.columns(4)
    overview[0].metric("Latest Price", "Unavailable" if live is None else f"{live:,.2f}")
    overview[1].metric("Bar Close", f"{signal['close']:,.2f}")
    overview[2].metric(f"EMA{fast_ema}", f"{signal['ema20']:,.2f}")
    overview[3].metric(f"EMA{slow_ema}", f"{signal['ema30']:,.2f}")

    st.dataframe(pd.DataFrame({"Condition":[f"Close above EMA{fast_ema}",f"Close above EMA{slow_ema}",f"EMA{fast_ema} above EMA{slow_ema}","Volume above average"],
                               "Result":[signal["above_ema20"],signal["above_ema30"],signal["ema_stack"],signal["volume_confirm"]]}), hide_index=True, width="stretch")
    st.caption(f"Signal bar: {signal['bar_date']} | Quote: {quote_time}")
with t3:
    c=st.columns(6)
    c[0].metric("Trades",metrics["trades"]); c[1].metric("Win Rate",f"{metrics['win_rate']:.1f}%")
    c[2].metric("Return",f"{metrics['return_pct']:.1f}%"); c[3].metric("Net Profit",f"{metrics['net_profit']:,.2f}")
    c[4].metric("Max Drawdown",f"{metrics['max_drawdown_pct']:.1f}%")
    c[5].metric("Transaction Costs",f"{metrics.get('total_costs', 0.0):,.2f}")
    if not trades.empty: st.dataframe(trades, width="stretch")
with t4:
    st.subheader("Signal scanner")
    st.caption("Filter by market, capitalization, and signal strength to find the best setups quickly.")
    scan_market = st.selectbox("Scanner Market", ["India", "US"], key="sm")
    scan_tf = st.radio("Scanner Timeframe", ["Daily", "Weekly", "Monthly", "Quarterly"], horizontal=True)
    st.markdown(
        """
        <div class="strategy-panel">
            <div class="strategy-panel-title">Strategy</div>
            <div class="strategy-panel-hint">Use the same setup rules shown in your strategy panel.</div>
            <div class="strategy-divider"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    scan_strategy_col1, scan_strategy_col2 = st.columns(2)
    scan_fast_ema = int(scan_strategy_col1.number_input("Fast EMA", min_value=2, max_value=200, value=20, step=1, key="scan_fast_ema"))
    scan_slow_ema = int(scan_strategy_col2.number_input("Slow EMA", min_value=3, max_value=300, value=50, step=1, key="scan_slow_ema"))
    scan_require_price_above_ema200 = st.checkbox("Require price > EMA 200", value=True, key="scan_require_price_above_ema200")

    if scan_slow_ema <= scan_fast_ema:
        st.warning("Scanner Slow EMA must be greater than Fast EMA.")

    scan_market_cap = st.selectbox("Market Cap", MARKET_CAP_OPTIONS, index=0, help="Mega Cap = $200B+, Large Cap = $10B-$200B, Mid Cap = $2B-$10B")
    signal_options = [
        "BREAKOUT BUY",
        "PULLBACK BUY",
        "DOUBLE DOJI SUPPORT BUY",
        "WATCH",
        "NEUTRAL",
        "DOUBLE DOJI RESISTANCE ALERT",
        "AVOID",
    ]
    default_signals = ["BREAKOUT BUY", "PULLBACK BUY", "DOUBLE DOJI SUPPORT BUY", "WATCH"]
    for option in signal_options:
        key_name = f"signal_filter_{option.replace(' ', '_')}"
        if key_name not in st.session_state:
            st.session_state[key_name] = option in default_signals
    signal_checkboxes = {}
    signal_cols = st.columns(4)
    for idx, option in enumerate(signal_options):
        with signal_cols[idx % 4]:
            signal_checkboxes[option] = st.checkbox(option, key=f"signal_filter_{option.replace(' ', '_')}")
    allowed = [option for option in signal_options if signal_checkboxes.get(option, False)]
    if not allowed:
        st.warning("Please select at least one signal type to scan.")
    f1, f2, f3, f4 = st.columns(4)
    rv = f1.checkbox("Require volume", value=True)
    e20 = f2.checkbox(f"Require close > EMA{scan_fast_ema}")
    e30 = f3.checkbox(f"Require close > EMA{scan_slow_ema}")
    stack = f4.checkbox(f"Require EMA{scan_fast_ema} > EMA{scan_slow_ema}")
    # Use the same mapping as the sidebar so UI labels ("US") map to CSV values ("USA")
    scan_market_value = MARKET_LABELS.get(scan_market, scan_market)
    sdf = symbols[symbols.market == scan_market_value]
    max_count = len(sdf)
    if max_count == 0:
        st.warning("No symbols available for the selected market.")
    else:
        min_count = 5 if max_count >= 5 else 1
        default_count = min(20, max_count)
        count = st.slider("Number of symbols", min_count, max_count, value=default_count)
        if "scanner_last_result" not in st.session_state:
            st.session_state["scanner_last_result"] = pd.DataFrame()
        if "scanner_last_failed" not in st.session_state:
            st.session_state["scanner_last_failed"] = pd.DataFrame()
        if st.button("Run Scanner"):
            if not allowed:
                st.warning("Please select at least one signal type to scan.")
            elif scan_slow_ema <= scan_fast_ema:
                st.warning("Scanner Slow EMA must be greater than Fast EMA.")
            else:
                with st.spinner("Scanning..."):
                    log_runtime_event("scanner_start")
                    result = run_scanner_cached(
                        sdf,
                        scan_tf,
                        count,
                        scan_fast_ema,
                        scan_slow_ema,
                        scan_require_price_above_ema200,
                    )
                    failed = result[result["Signal"] == "ERROR"].copy()
                    st.session_state["scanner_last_failed"] = failed.copy()
                    filtered = result[result.Signal.isin(allowed)].copy()
                    if scan_market_cap != "All":
                        filtered = filtered[filtered["Market Cap Bucket"] == scan_market_cap]
                    if rv:
                        filtered = filtered[filtered["Volume Confirm"] == True]
                    if e20:
                        filtered = filtered[filtered["Close > EMA20"] == True]
                    if e30:
                        filtered = filtered[filtered["Close > EMA30"] == True]
                    if stack:
                        filtered = filtered[filtered["EMA20 > EMA30"] == True]
                    st.session_state["scanner_last_result"] = filtered.copy()
                    log_runtime_event("scanner_done")

        filtered = st.session_state.get("scanner_last_result", pd.DataFrame()).copy()
        failed = st.session_state.get("scanner_last_failed", pd.DataFrame()).copy()

        sector_selection = []
        industry_selection = []
        if not filtered.empty:
            filter_cols = st.columns(2)
            available_sectors = sorted([s for s in filtered.get("Sector", pd.Series(dtype=str)).dropna().astype(str).unique() if s])
            available_industries = sorted([s for s in filtered.get("Industry", pd.Series(dtype=str)).dropna().astype(str).unique() if s])
            sector_selection = filter_cols[0].multiselect("Filter Sector", available_sectors, default=[])
            industry_selection = filter_cols[1].multiselect("Filter Industry", available_industries, default=[])

            if sector_selection:
                filtered = filtered[filtered["Sector"].isin(sector_selection)]
            if industry_selection:
                filtered = filtered[filtered["Industry"].isin(industry_selection)]

        total_filtered = len(filtered)
        st.markdown(f"**Results:** {total_filtered} matching symbol{'s' if total_filtered != 1 else ''}")
        if not failed.empty:
            st.warning(f"Skipped {len(failed)} symbol{'s' if len(failed) != 1 else ''} due to data errors.")
            with st.expander("Failed Symbols"):
                failed_view = failed[["Symbol", "Quote Symbol", "Error"]].copy()
                st.dataframe(failed_view, hide_index=True, width="stretch")
        if filtered.empty:
            st.info("Run scanner to load results with current filters.")
        else:
            sort_order = st.selectbox(
                "Sort results by",
                [
                    "Setup Score (High to Low)",
                    "Setup Score (Low to High)",
                    "Market Cap (High to Low)",
                    "Market Cap (Low to High)",
                    "Signal (Best to Worst)",
                    "Signal (Worst to Best)",
                    "Bar Date (Latest First)",
                    "Bar Date (Oldest First)",
                    "Ticker (A-Z)",
                    "Ticker (Z-A)",
                ],
                key="scanner_sort_order",
            )

            display_df = filtered.copy()
            required_defaults = {
                "Company Name": "Unknown",
                "Ticker": "",
                "Quote Symbol": "",
                "Market": "Unknown",
                "Sector": "Unknown",
                "Industry": "Unknown",
                "Market Cap": "N/A",
                "Market Cap Value": 0.0,
                "Market Cap Bucket": "Unknown",
                "Cap Tier": "Unknown",
                "Signal": "UNKNOWN",
                "Bar Date": "",
                "Setup Score": 0.0,
                "Trend Score": 0.0,
                "Volume Ratio": 0.0,
                "Distance to EMA20 %": 0.0,
                "Close > EMA200": False,
                "Close > EMA20": False,
                "Close > EMA30": False,
                "EMA20 > EMA30": False,
                "Volume Confirm": False,
            }
            for col, default in required_defaults.items():
                if col not in display_df.columns:
                    display_df[col] = default

            if "Market Cap Value" in display_df.columns:
                display_df["Market Cap"] = display_df["Market Cap Value"].apply(
                    lambda v: (
                        f"{v/1_000_000_000_000:.1f}T" if v and v >= 1_000_000_000_000
                        else f"{v/1_000_000_000:.1f}B" if v and v >= 1_000_000_000
                        else f"{v/1_000_000:.1f}M" if v and v >= 1_000_000
                        else f"{v:,.0f}"
                    )
                )
                display_df["Cap Tier"] = display_df["Market Cap Bucket"].astype(str)
            display_df["Ticker"] = display_df["Symbol"].astype(str)
            display_df["Quote Symbol"] = display_df.apply(quote_symbol_for_row, axis=1)
            display_df["Company Name"] = display_df["Quote Symbol"].apply(
                company_name_from_ticker
            )
            display_df["Yahoo"] = "https://finance.yahoo.com/quote/" + display_df["Quote Symbol"]
            display_df["TradingView"] = "https://www.tradingview.com/symbols/" + display_df["Quote Symbol"] + "/"

            display_df["Setup Score"] = pd.to_numeric(
                display_df.get("Setup Score", pd.Series(index=display_df.index, dtype=float)),
                errors="coerce",
            ).fillna(0.0)
            display_df["Trend Score"] = pd.to_numeric(
                display_df.get("Trend Score", pd.Series(index=display_df.index, dtype=float)),
                errors="coerce",
            ).fillna(0.0)
            display_df["Volume Ratio"] = pd.to_numeric(
                display_df.get("Volume Ratio", pd.Series(index=display_df.index, dtype=float)),
                errors="coerce",
            ).fillna(0.0)
            display_df["Distance to EMA20 %"] = pd.to_numeric(
                display_df.get("Distance to EMA20 %", pd.Series(index=display_df.index, dtype=float)),
                errors="coerce",
            ).fillna(0.0)

            signal_rank = {
                "BREAKOUT BUY": 1,
                "PULLBACK BUY": 2,
                "DOUBLE DOJI SUPPORT BUY": 3,
                "WATCH": 4,
                "NEUTRAL": 5,
                "DOUBLE DOJI RESISTANCE ALERT": 6,
                "AVOID": 7,
                "ERROR": 9,
            }
            display_df["_signal_rank"] = display_df["Signal"].map(signal_rank).fillna(99)
            display_df["_bar_date"] = pd.to_datetime(display_df["Bar Date"], errors="coerce")

            if sort_order == "Setup Score (High to Low)":
                display_df = display_df.sort_values(["Setup Score", "_signal_rank", "Market Cap Value"], ascending=[False, True, False], na_position="last")
            elif sort_order == "Setup Score (Low to High)":
                display_df = display_df.sort_values(["Setup Score", "_signal_rank", "Market Cap Value"], ascending=[True, True, False], na_position="last")
            elif sort_order == "Market Cap (High to Low)" and "Market Cap Value" in display_df.columns:
                display_df = display_df.sort_values(["Market Cap Value", "_signal_rank"], ascending=[False, True], na_position="last")
            elif sort_order == "Market Cap (Low to High)" and "Market Cap Value" in display_df.columns:
                display_df = display_df.sort_values(["Market Cap Value", "_signal_rank"], ascending=[True, True], na_position="last")
            elif sort_order == "Signal (Best to Worst)":
                display_df = display_df.sort_values(["_signal_rank", "Market Cap Value"], ascending=[True, False], na_position="last")
            elif sort_order == "Signal (Worst to Best)":
                display_df = display_df.sort_values(["_signal_rank", "Market Cap Value"], ascending=[False, False], na_position="last")
            elif sort_order == "Bar Date (Latest First)":
                display_df = display_df.sort_values(["_bar_date", "_signal_rank"], ascending=[False, True], na_position="last")
            elif sort_order == "Bar Date (Oldest First)":
                display_df = display_df.sort_values(["_bar_date", "_signal_rank"], ascending=[True, True], na_position="last")
            elif sort_order == "Ticker (A-Z)":
                display_df = display_df.sort_values(["Ticker"], ascending=[True], na_position="last")
            elif sort_order == "Ticker (Z-A)":
                display_df = display_df.sort_values(["Ticker"], ascending=[False], na_position="last")

            display_df = display_df.drop(columns=["_signal_rank", "_bar_date"], errors="ignore")
            display_df = display_df.reset_index(drop=True)
            view_df = display_df[[
                "Company Name",
                "Ticker",
                "Market",
                "Sector",
                "Industry",
                "Market Cap",
                "Cap Tier",
                "Signal",
                "Setup Score",
                "Trend Score",
                "Volume Ratio",
                "Bar Date",
                "Yahoo",
                "TradingView",
            ]].copy()
            st.session_state["scanner_last_display"] = display_df.copy()

            result_view_mode = st.radio(
                "Result View",
                ["Table", "Cards"],
                horizontal=True,
                key="scanner_result_view_mode",
            )
            if result_view_mode == "Cards":
                render_scanner_cards(view_df, scan_market)
            else:
                render_scanner_table(view_df, scan_market)

            with st.expander("Why this signal", expanded=False):
                explain_options = (
                    display_df["Quote Symbol"].astype(str)
                    + " • "
                    + display_df["Signal"].astype(str)
                    + " • score "
                    + display_df["Setup Score"].astype(float).map(lambda x: f"{x:.1f}")
                ).tolist()
                explain_pick = st.selectbox("Select symbol", explain_options, key="scanner_signal_explain_pick")
                explain_row = display_df.iloc[explain_options.index(explain_pick)]
                explain_df = build_signal_explanation(explain_row)
                st.dataframe(explain_df, hide_index=True, width="stretch")

            watchlists = st.session_state["watchlists"]
            watchlist_names = list_watchlist_names(watchlists)
            top_limit = min(20, len(display_df))

            wl_cols = st.columns([2, 2, 2, 1])
            selected_watchlist = wl_cols[0].selectbox(
                "Watchlist",
                watchlist_names,
                key="scanner_watchlist_target",
            )
            ticker_pick = wl_cols[1].selectbox(
                "Ticker to add",
                display_df["Quote Symbol"].astype(str).tolist(),
                key="scanner_watchlist_ticker_pick",
            )
            top_n = wl_cols[2].slider("Top N", 1, top_limit, min(5, top_limit), key="scanner_watchlist_top_n")

            if wl_cols[3].button("Add Ticker"):
                selected_rows = display_df[display_df["Quote Symbol"] == ticker_pick].head(1).to_dict("records")
                added = add_symbols_to_watchlist(watchlists, selected_watchlist, selected_rows)
                save_watchlists(watchlists)
                st.success(f"Added {added} symbol to watchlist '{selected_watchlist}'.")

            if st.button("Add Top N to Watchlist"):
                selected_rows = display_df.head(top_n).to_dict("records")
                added = add_symbols_to_watchlist(watchlists, selected_watchlist, selected_rows)
                save_watchlists(watchlists)
                st.success(f"Added {added} symbols to watchlist '{selected_watchlist}'.")

            st.download_button("Download CSV", display_df.to_csv(index=False).encode(), file_name=f"{scan_market}_{scan_tf}_{scan_market_cap.lower().replace(' ', '_')}_signals.csv")

with t5:
    st.subheader("Watchlists")
    watchlists = st.session_state["watchlists"]
    watchlist_names = list_watchlist_names(watchlists)

    manage_cols = st.columns([2, 2, 1, 1])
    active_name = manage_cols[0].selectbox(
        "Select watchlist",
        watchlist_names,
        index=watchlist_names.index(st.session_state.get("watchlist_active_name", watchlist_names[0])) if watchlist_names else 0,
        key="watchlist_active_select",
    )
    st.session_state["watchlist_active_name"] = active_name

    new_watchlist_name = manage_cols[1].text_input("Create watchlist", value="", placeholder="Example: US Swing")
    if manage_cols[2].button("Create"):
        if create_watchlist(watchlists, new_watchlist_name):
            save_watchlists(watchlists)
            st.success(f"Created watchlist '{new_watchlist_name.strip()}'.")
        else:
            st.warning("Enter a unique watchlist name.")

    if manage_cols[3].button("Delete"):
        if delete_watchlist(watchlists, active_name):
            save_watchlists(watchlists)
            st.success(f"Deleted watchlist '{active_name}'.")
            names = list_watchlist_names(watchlists)
            st.session_state["watchlist_active_name"] = names[0]
            st.rerun()
        else:
            st.warning("Cannot delete the last remaining watchlist.")

    active_rows = watchlists.get(active_name, [])
    watch_df = pd.DataFrame(active_rows)

    latest_scanner = st.session_state.get("scanner_last_display", pd.DataFrame()).copy()
    if not watch_df.empty and not latest_scanner.empty:
        latest_scanner = latest_scanner.drop_duplicates(subset=["Quote Symbol"], keep="first")
        refresh_cols = ["Quote Symbol", "Signal", "Setup Score", "Bar Date", "Sector", "Industry", "Market"]
        merge_df = latest_scanner[refresh_cols].copy()
        watch_df = watch_df.drop(columns=[c for c in refresh_cols if c != "Quote Symbol" and c in watch_df.columns], errors="ignore")
        watch_df = watch_df.merge(merge_df, on="Quote Symbol", how="left")
        watch_df["Signal"] = watch_df["Signal"].fillna("Unknown")
        watch_df["Setup Score"] = pd.to_numeric(watch_df["Setup Score"], errors="coerce").fillna(0.0)

    if watch_df.empty:
        st.info("This watchlist is empty. Add symbols from the scanner tab.")
    else:
        mcols = st.columns(4)
        mcols[0].metric("Symbols", len(watch_df))
        mcols[1].metric("Average Score", f"{watch_df['Setup Score'].astype(float).mean():.1f}")
        mcols[2].metric("Breakout Buy", int((watch_df["Signal"] == "BREAKOUT BUY").sum()))
        mcols[3].metric("Pullback Buy", int((watch_df["Signal"] == "PULLBACK BUY").sum()))

        watchlist_view = st.radio("Watchlist View", ["Table", "Board"], horizontal=True, key="watchlist_view_mode")

        if watchlist_view == "Board":
            signal_order = [
                "BREAKOUT BUY",
                "PULLBACK BUY",
                "DOUBLE DOJI SUPPORT BUY",
                "WATCH",
                "NEUTRAL",
                "DOUBLE DOJI RESISTANCE ALERT",
                "AVOID",
                "Unknown",
            ]
            groups: list[tuple[str, pd.DataFrame]] = []
            seen = set()
            for label in signal_order:
                part = watch_df[watch_df["Signal"].fillna("Unknown") == label]
                if not part.empty:
                    groups.append((label, part))
                    seen.add(label)
            for extra in sorted(set(watch_df["Signal"].fillna("Unknown").astype(str).tolist()) - seen):
                part = watch_df[watch_df["Signal"].fillna("Unknown") == extra]
                if not part.empty:
                    groups.append((extra, part))

            if not groups:
                st.info("No grouped watchlist items to display.")
            else:
                board_cols = st.columns(min(3, len(groups)))
                for idx, (label, part) in enumerate(groups):
                    with board_cols[idx % len(board_cols)]:
                        st.markdown(f"**{label}** ({len(part)})")
                        for _, row in part.sort_values("Setup Score", ascending=False).iterrows():
                            sym = str(row.get("Quote Symbol") or "")
                            score = float(pd.to_numeric(row.get("Setup Score"), errors="coerce") or 0.0)
                            sector = str(row.get("Sector") or "Unknown")
                            industry = str(row.get("Industry") or "Unknown")
                            st.markdown(
                                (
                                    "<div style='background:rgba(15,23,42,0.62);border:1px solid rgba(148,163,184,0.16);"
                                    "border-radius:10px;padding:0.45rem 0.55rem;margin:0.35rem 0;'>"
                                    f"<div style='font-weight:700;color:#e8edf8;'>{html_lib.escape(sym)}</div>"
                                    f"<div style='font-size:0.78rem;color:#cbd5e1;'>Score {score:.1f} • {html_lib.escape(sector)}</div>"
                                    f"<div style='font-size:0.74rem;color:#94a3b8;'>{html_lib.escape(industry)}</div>"
                                    "</div>"
                                ),
                                unsafe_allow_html=True,
                            )

        sector_summary = (
            watch_df["Sector"]
            .fillna("Unknown")
            .value_counts()
            .rename_axis("Sector")
            .reset_index(name="Count")
        )
        with st.expander("Sector Distribution", expanded=False):
            st.dataframe(sector_summary, hide_index=True, width="stretch")

        remove_cols = st.columns([3, 1])
        remove_symbol = remove_cols[0].selectbox("Remove symbol", watch_df["Quote Symbol"].astype(str).tolist(), key="watchlist_remove_pick")
        if remove_cols[1].button("Remove"):
            if remove_symbol_from_watchlist(watchlists, active_name, remove_symbol):
                save_watchlists(watchlists)
                st.success(f"Removed {remove_symbol} from '{active_name}'.")
                st.rerun()

        if watchlist_view == "Table":
            st.dataframe(watch_df, hide_index=True, width="stretch")
        else:
            with st.expander("Open Table View", expanded=False):
                st.dataframe(watch_df, hide_index=True, width="stretch")
        st.download_button(
            "Export Watchlist CSV",
            watch_df.to_csv(index=False).encode(),
            file_name=f"{active_name.lower().replace(' ', '_')}_watchlist.csv",
        )

    upload_file = st.file_uploader("Import Watchlist CSV", type=["csv"], key="watchlist_import_csv")
    if upload_file is not None:
        import_df = pd.read_csv(upload_file)
        if import_df.empty:
            st.warning("Uploaded CSV is empty.")
        else:
            if "Quote Symbol" not in import_df.columns:
                if "Ticker" in import_df.columns:
                    import_df["Quote Symbol"] = import_df["Ticker"]
                elif "Symbol" in import_df.columns:
                    import_df["Quote Symbol"] = import_df["Symbol"]
            if "Quote Symbol" not in import_df.columns:
                st.error("CSV must include Quote Symbol, Ticker, or Symbol column.")
            else:
                added = add_symbols_to_watchlist(watchlists, active_name, import_df.to_dict("records"))
                save_watchlists(watchlists)
                st.success(f"Imported {added} symbols into '{active_name}'.")

with t6:
    st.subheader("Assistant")
    st.caption("Ask for quick summaries from current scanner, watchlist, and backtest context.")
    scanner_df = st.session_state.get("scanner_last_display", pd.DataFrame()).copy()
    watchlists = st.session_state.get("watchlists", {})
    active_name = st.session_state.get("watchlist_active_name", "Default")
    watch_df = pd.DataFrame(watchlists.get(active_name, []))

    question = st.text_input("Ask assistant", placeholder="Example: top 5 scanner setups")
    if st.button("Ask"):
        reply = build_assistant_reply(question, scanner_df, watch_df, signal, metrics)
        st.info(reply)

    st.markdown("**Suggested prompts**")
    st.write("- top 5 scanner setups")
    st.write("- watchlist summary")
    st.write("- current signal")
    st.write("- backtest return")
    st.write("- compare NVDA vs AAPL")
    st.write("- risk summary")
st.caption("Educational research tool only. Data may be delayed.")
