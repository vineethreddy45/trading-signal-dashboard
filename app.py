from pathlib import Path
import html as html_lib
from urllib.parse import quote_plus
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from src.market_data import download_history, latest_price
from src.scanner import scan_symbols
from src.strategy import StrategyConfig, backtest, convert_timeframe, enrich, latest_signal

st.set_page_config(page_title="Trading Signal Dashboard", layout="wide")

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
            "<th style='text-align:left;padding:8px;'>Market Cap</th>"
            "<th style='text-align:left;padding:8px;'>Cap Tier</th>"
            "<th style='text-align:left;padding:8px;'>Signal</th>"
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
        market_cap = html_lib.escape(str(row["Market Cap"]))
        cap_tier = html_lib.escape(str(row["Cap Tier"]))
        signal = html_lib.escape(str(row["Signal"]))
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
                f"<td style='padding:8px;'>{market_cap}</td>"
                f"<td style='padding:8px;'>{cap_tier}</td>"
                f"<td style='padding:8px;'>{signal}</td>"
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
    st.session_state["symbol_selector"] = None
    st.session_state["timeframe_selector"] = None
    st.session_state["_defaults_initialized"] = True
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
            symbol_index = None
            if selected_symbol_state is not None:
                current_match = filtered_df[
                    filtered_df["symbol"].astype(str).str.upper() == str(selected_symbol_state).upper()
                ]
                if not current_match.empty:
                    default_display = current_match.iloc[0]["display_symbol"]
                    symbol_index = display_options.index(default_display)

            display = st.selectbox(
                "Symbol",
                display_options,
                index=symbol_index,
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
    st.caption("Market cap guide: Mega Cap = $200B+, Large Cap = $10B-$200B, Mid Cap = $2B-$10B.")


if not market or not symbol or not timeframe:
    st.info("Select Market, Symbol, and Timeframe from the sidebar to load the dashboard.")
    st.stop()


cfg = StrategyConfig(timeframe=timeframe, capital=capital)
try:
    daily = load_history(symbol, period)
    bars = convert_timeframe(daily, timeframe)
    chart_data = enrich(bars, cfg)
    signal = latest_signal(bars, cfg)
    trades, equity, metrics = backtest(bars, cfg)
except Exception as exc:
    st.error(str(exc))
    st.stop()


t1, t3, t4 = st.tabs(["Overview", "Backtest", "Signal Scanner"])
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
    c=st.columns(5)
    c[0].metric("Trades",metrics["trades"]); c[1].metric("Win Rate",f"{metrics['win_rate']:.1f}%")
    c[2].metric("Return",f"{metrics['return_pct']:.1f}%"); c[3].metric("Net Profit",f"{metrics['net_profit']:,.2f}")
    c[4].metric("Max Drawdown",f"{metrics['max_drawdown_pct']:.1f}%")
    if not trades.empty: st.dataframe(trades, width="stretch")
with t4:
    st.subheader("Signal scanner")
    st.caption("Filter by market, capitalization, and signal strength to find the best setups quickly.")
    scan_market = st.selectbox("Scanner Market", ["India", "US"], key="sm")
    scan_tf = st.radio("Scanner Timeframe", ["Daily", "Weekly"], horizontal=True)
    scan_market_cap = st.selectbox("Market Cap", MARKET_CAP_OPTIONS, index=0, help="Mega Cap = $200B+, Large Cap = $10B-$200B, Mid Cap = $2B-$10B")
    signal_options = ["BREAKOUT BUY", "PULLBACK BUY", "WATCH", "NEUTRAL", "AVOID"]
    default_signals = ["BREAKOUT BUY", "PULLBACK BUY", "WATCH"]
    signal_checkboxes = {}
    signal_cols = st.columns(4)
    for idx, option in enumerate(signal_options):
        with signal_cols[idx % 4]:
            signal_checkboxes[option] = st.checkbox(option, value=option in default_signals, key=f"signal_filter_{option.replace(' ', '_')}")
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
        filtered = pd.DataFrame()
        if st.button("Run Scanner"):
            if not allowed:
                st.warning("Please select at least one signal type to scan.")
            else:
                with st.spinner("Scanning..."):
                    result = scan_symbols(sdf, scan_tf, count)
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
                    total_filtered = len(filtered)
                    st.markdown(f"**Results:** {total_filtered} matching symbol{'s' if total_filtered != 1 else ''}")
                    if filtered.empty:
                        st.info("No symbols matched the selected filters. Try fewer restrictions.")
                    else:
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
                        display_df["Company Name"] = display_df["Ticker"].apply(
                            lambda ticker: (
                                yf.Ticker(ticker).info.get("shortName") or ticker
                            ) if str(ticker).strip() else ticker
                        )
                        display_df["Yahoo"] = "https://finance.yahoo.com/quote/" + display_df["Ticker"]
                        display_df["TradingView"] = "https://www.tradingview.com/symbols/" + display_df["Ticker"] + "/"
                        if "Market Cap Value" in display_df.columns:
                            display_df = display_df.sort_values(["Market Cap Value", "Signal"], ascending=[False, True], na_position="last").copy()
                        display_df = display_df.reset_index(drop=True)
                        view_df = display_df[["Company Name", "Ticker", "Market", "Market Cap", "Cap Tier", "Signal", "Bar Date", "Yahoo", "TradingView"]].copy()
                        render_scanner_table(view_df, scan_market)
                        st.download_button("Download CSV", filtered.to_csv(index=False).encode(), file_name=f"{scan_market}_{scan_tf}_{scan_market_cap.lower().replace(' ', '_')}_signals.csv")
st.caption("Educational research tool only. Data may be delayed.")
