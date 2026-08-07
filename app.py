from pathlib import Path
import html as html_lib
import logging
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


def build_assistant_reply(
    query: str,
    scanner_df: pd.DataFrame,
    watchlist_df: pd.DataFrame,
    current_signal: dict,
    metrics: dict,
) -> str:
    q = str(query).strip().lower()
    if not q:
        return "Ask about top setups, current signal status, watchlist summary, or backtest metrics."

    if "top" in q and ("scanner" in q or "setup" in q or "symbols" in q):
        if scanner_df.empty:
            return "Scanner results are empty. Run scanner first, then ask for top setups."
        top = scanner_df.sort_values("Setup Score", ascending=False).head(5)
        rows = [
            f"{r['Quote Symbol']} ({r['Signal']}) score {float(r.get('Setup Score', 0.0)):.1f}"
            for _, r in top.iterrows()
        ]
        return "Top scanner setups:\n" + "\n".join(rows)

    if "watchlist" in q:
        if watchlist_df.empty:
            return "Your selected watchlist is empty. Add symbols from the scanner tab."
        sector_count = watchlist_df["Sector"].fillna("Unknown").value_counts().head(3)
        sector_text = ", ".join([f"{name} ({count})" for name, count in sector_count.items()])
        avg_score = pd.to_numeric(watchlist_df.get("Setup Score"), errors="coerce").fillna(0.0).mean()
        return (
            f"Watchlist has {len(watchlist_df)} symbols. "
            f"Average setup score is {avg_score:.1f}. "
            f"Top sectors: {sector_text}."
        )

    if "signal" in q or "current" in q:
        return (
            f"Current chart signal is {current_signal['signal']}. "
            f"Close {current_signal['close']:.2f}, EMA20 {current_signal['ema20']:.2f}, "
            f"EMA30 {current_signal['ema30']:.2f}, volume confirm={current_signal['volume_confirm']}."
        )

    if "backtest" in q or "return" in q:
        return (
            f"Backtest metrics: trades={metrics['trades']}, win rate={metrics['win_rate']:.1f}%, "
            f"return={metrics['return_pct']:.1f}%, max drawdown={metrics['max_drawdown_pct']:.1f}%, "
            f"transaction costs={metrics.get('total_costs', 0.0):,.2f}."
        )

    return (
        "Try asking: 'top 5 scanner setups', 'watchlist summary', 'current signal', or 'backtest return'."
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
def run_scanner_cached(symbols_df: pd.DataFrame, timeframe: str, count: int) -> pd.DataFrame:
    return scan_symbols(symbols_df, timeframe, count)


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

        if filtered_df.empty:
            st.warning("No matching symbol found. Try a different search term.")
        else:
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
    else:
        st.selectbox("Symbol", [], index=None, key="symbol_selector", placeholder="Select market first")

    timeframe = st.radio(
        "Timeframe",
        ["Daily", "Weekly"],
        horizontal=True,
        index=None,
        key="timeframe_selector",
    )
    period = st.selectbox("History", ["1y", "3y", "5y", "max"], index=0)
    capital = st.number_input("Capital", min_value=1000.0, value=1_000_000.0 if market=="India" else 10_000.0, step=1000.0)
    c1, c2 = st.columns(2)
    commission_pct = c1.number_input("Commission %", min_value=0.0, max_value=2.0, value=0.05, step=0.01)
    slippage_pct = c2.number_input("Slippage %", min_value=0.0, max_value=2.0, value=0.05, step=0.01)
    st.caption("Market cap guide: Mega Cap = $200B+, Large Cap = $10B-$200B, Mid Cap = $2B-$10B.")


if not market or not symbol or not timeframe:
    st.info("Select Market, Symbol, and Timeframe from the sidebar to load the dashboard.")
    st.stop()


cfg = StrategyConfig(
    timeframe=timeframe,
    capital=capital,
    commission_pct=float(commission_pct),
    slippage_pct=float(slippage_pct),
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
    overview[2].metric("EMA20", f"{signal['ema20']:,.2f}")
    overview[3].metric("EMA30", f"{signal['ema30']:,.2f}")

    st.dataframe(pd.DataFrame({"Condition":["Close above EMA20","Close above EMA30","EMA20 above EMA30","Volume above average"],
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
    scan_tf = st.radio("Scanner Timeframe", ["Daily", "Weekly"], horizontal=True)
    scan_market_cap = st.selectbox("Market Cap", MARKET_CAP_OPTIONS, index=0, help="Mega Cap = $200B+, Large Cap = $10B-$200B, Mid Cap = $2B-$10B")
    signal_options = ["BREAKOUT BUY", "PULLBACK BUY", "WATCH", "NEUTRAL", "AVOID"]
    default_signals = ["BREAKOUT BUY", "PULLBACK BUY", "WATCH"]
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
    e20 = f2.checkbox("Require close > EMA20")
    e30 = f3.checkbox("Require close > EMA30")
    stack = f4.checkbox("Require EMA20 > EMA30")
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
            else:
                with st.spinner("Scanning..."):
                    log_runtime_event("scanner_start")
                    result = run_scanner_cached(sdf, scan_tf, count)
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
                "WATCH": 3,
                "NEUTRAL": 4,
                "AVOID": 5,
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
            render_scanner_table(view_df, scan_market)

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
st.caption("Educational research tool only. Data may be delayed.")
