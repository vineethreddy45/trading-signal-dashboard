from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src.market_data import download_history, latest_price
from src.scanner import scan_symbols
from src.strategy import StrategyConfig, backtest, convert_timeframe, enrich, latest_signal

st.set_page_config(page_title="Trading Signal Dashboard", layout="wide")
st.title("Trading Signal Dashboard")
st.caption("Daily and Weekly Swing Tradesignals")

# Map UI market names to CSV market values
MARKET_LABELS = {"India": "India", "US": "USA"}


@st.cache_data(ttl=3600)
def load_symbols():
    return pd.read_csv(Path("data/symbols.csv"))


@st.cache_data(ttl=3600, show_spinner=False)
def load_history(symbol, period):
    return download_history(symbol, period)


symbols = load_symbols()
with st.sidebar:
    market = st.selectbox("Market", list(MARKET_LABELS.keys()), index=1)
    market_value = MARKET_LABELS[market]
    market_df = symbols[symbols.market == market_value]

    search_query = st.text_input("Search symbol", value="")
    if search_query:
        filtered_df = market_df[
            market_df["display_symbol"].str.contains(search_query, case=False, na=False)
            | market_df["symbol"].str.contains(search_query, case=False, na=False)
        ]
    else:
        filtered_df = market_df

    if filtered_df.empty:
        st.warning("No matching symbol found. Try a different search term.")
        st.stop()

    display = st.selectbox("Symbol", filtered_df.display_symbol.tolist())
    symbol = filtered_df.loc[filtered_df.display_symbol == display, "symbol"].iloc[0]
    timeframe = st.radio("Timeframe", ["Daily", "Weekly"], horizontal=True)
    period = st.selectbox("History", ["1y", "3y", "5y", "max"], index=1)
    capital = st.number_input("Capital", min_value=1000.0, value=1_000_000.0 if market=="India" else 10_000.0, step=1000.0)
    risk_pct = st.slider("Risk per trade (%)", 0.25, 2.0, 1.0, 0.25)
    target_r = st.slider("Target R", 1.0, 5.0, 2.0, 0.5)
    stop_lookback = st.slider("Stop lookback", 1, 10, 2 if timeframe=="Weekly" else 5)


cfg = StrategyConfig(timeframe=timeframe, capital=capital, risk_pct=risk_pct, target_r=target_r, stop_lookback=stop_lookback)
try:
    daily = load_history(symbol, period)
    bars = convert_timeframe(daily, timeframe)
    chart_data = enrich(bars, cfg)
    signal = latest_signal(bars, cfg)
    trades, equity, metrics = backtest(bars, cfg)
except Exception as exc:
    st.error(str(exc))
    st.stop()


t1,t2,t3,t4 = st.tabs(["Current Signal","Chart","Backtest","Signal Scanner"])
with t1:
    try:
        live, quote_time = latest_price(symbol)
    except Exception:
        live, quote_time = None, "Unavailable"
    cols = st.columns(5)
    cols[0].metric("Latest Price", "Unavailable" if live is None else f"{live:,.2f}")
    cols[1].metric("Bar Close", f"{signal['close']:,.2f}")
    cols[2].metric("EMA20", f"{signal['ema20']:,.2f}")
    cols[3].metric("EMA30", f"{signal['ema30']:,.2f}")
    cols[4].metric("Signal", signal["signal"])
    st.dataframe(pd.DataFrame({"Condition":["Close above EMA20","Close above EMA30","EMA20 above EMA30","Volume above average"],
                               "Result":[signal["above_ema20"],signal["above_ema30"],signal["ema_stack"],signal["volume_confirm"]]}), hide_index=True, use_container_width=True)
    st.caption(f"Signal bar: {signal['bar_date']} | Quote: {quote_time}")
with t2:
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=chart_data.index,open=chart_data.Open,high=chart_data.High,low=chart_data.Low,close=chart_data.Close,name=display))
    fig.add_trace(go.Scatter(x=chart_data.index,y=chart_data.EMA20,name="EMA20"))
    fig.add_trace(go.Scatter(x=chart_data.index,y=chart_data.EMA30,name="EMA30"))
    br, pb = chart_data[chart_data.BREAKOUT_BUY], chart_data[chart_data.PULLBACK_BUY]
    fig.add_trace(go.Scatter(x=br.index,y=br.Low,mode="markers",marker={"symbol":"triangle-up","size":11},name="Breakout Buy"))
    fig.add_trace(go.Scatter(x=pb.index,y=pb.Low,mode="markers",marker={"symbol":"circle","size":8},name="Pullback Buy"))
    fig.update_layout(height=650,xaxis_rangeslider_visible=False)
    st.plotly_chart(fig,use_container_width=True)
with t3:
    c=st.columns(5)
    c[0].metric("Trades",metrics["trades"]); c[1].metric("Win Rate",f"{metrics['win_rate']:.1f}%")
    c[2].metric("Return",f"{metrics['return_pct']:.1f}%"); c[3].metric("Net Profit",f"{metrics['net_profit']:,.2f}")
    c[4].metric("Max Drawdown",f"{metrics['max_drawdown_pct']:.1f}%")
    if not equity.empty: st.line_chart(equity.Equity)
    if not trades.empty: st.dataframe(trades,use_container_width=True)
with t4:
    scan_market = st.selectbox("Scanner Market",["India","US"],key="sm")
    scan_tf = st.radio("Scanner Timeframe",["Daily","Weekly"],horizontal=True)
    allowed = st.multiselect("Signals",["BREAKOUT BUY","PULLBACK BUY","WATCH","NEUTRAL","AVOID"],default=["BREAKOUT BUY","PULLBACK BUY","WATCH"])
    if not allowed:
        st.warning("Please select at least one signal type to scan.")
    f1,f2,f3,f4=st.columns(4)
    rv=f1.checkbox("Require volume", value=True); e20=f2.checkbox("Require close > EMA20"); e30=f3.checkbox("Require close > EMA30"); stack=f4.checkbox("Require EMA20 > EMA30")
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
                        st.dataframe(filtered, hide_index=True, use_container_width=True)
                        st.download_button("Download CSV", filtered.to_csv(index=False).encode(), file_name=f"{scan_market}_{scan_tf}_signals.csv")
st.caption("Educational research tool only. Data may be delayed.")
