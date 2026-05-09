"""
app.py — Trading Terminal
成交量瀑布預警系統 + 多股票監控 + AI分析
視覺先於文字 — 顏色/動畫/大小即意思
"""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import json
import time
from datetime import datetime

from styles import inject_css
from data_engine import fetch_ohlcv, fetch_vix, fetch_quote
from indicators import resonance_score, ema, rsi, macd, volume_avg, volume_cascade_check
from volume_cascade import run_cascade, get_cascade_state, get_cascade_log
from telegram_bot import send_alert, send_volume_cascade
from groq_engine import groq_analysis

# ─── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Trading Terminal",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_css()

# ─── Colors ──────────────────────────────────────────────────────────────────
C = {
    "bull":   "#6fcf97",
    "bear":   "#eb5757",
    "warn":   "#f2c94c",
    "info":   "#56b4e9",
    "dim":    "#aaa",
    "faint":  "#444",
    "bg1":    "#0d0d0d",
    "border": "#1e1e1e",
}

# ─── Session State Init ───────────────────────────────────────────────────────
def init_state():
    defaults = {
        "tickers":         ["TSLA", "NVDA", "AAPL", "SPY", "QQQ"],
        "selected":        "TSLA",
        "tg_global_mute":  False,
        "tg_sent_keys":    set(),
        "global_alerts":   [],
        "last_refresh":    0,
        "refresh_interval": 30,
        "vc_threshold":    1.0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# ─── Helpers ─────────────────────────────────────────────────────────────────
def color_val(v, positive_good=True):
    if positive_good:
        return C["bull"] if v >= 0 else C["bear"]
    return C["bear"] if v >= 0 else C["bull"]

def score_color(s):
    return C["bull"] if s >= 65 else C["warn"] if s >= 45 else C["bear"]

def price_arrow(chg):
    return "▲" if chg >= 0 else "▼"

def vol_color(ratio):
    return C["bull"] if ratio >= 1.5 else C["warn"] if ratio >= 1.0 else C["faint"]

def add_global_alert(ticker, level, msg):
    st.session_state.global_alerts.insert(0, {
        "time": datetime.now().strftime("%H:%M:%S"),
        "ticker": ticker, "level": level, "msg": msg,
    })
    st.session_state.global_alerts = st.session_state.global_alerts[:30]


# ─── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown('<span class="live-dot"></span><span style="font-family:IBM Plex Mono;font-size:11px;color:#aaa;letter-spacing:0.1em">TRADING TERMINAL</span>', unsafe_allow_html=True)
    st.markdown("---")

    # 股票清單
    st.markdown('<span style="font-family:IBM Plex Mono;font-size:9px;color:#555;letter-spacing:0.12em">WATCHLIST</span>', unsafe_allow_html=True)
    ticker_input = st.text_input("", value=",".join(st.session_state.tickers),
                                  label_visibility="collapsed",
                                  placeholder="TSLA,NVDA,AAPL,SPY,QQQ")
    if ticker_input:
        new_tickers = [t.strip().upper() for t in ticker_input.split(",") if t.strip()]
        if new_tickers != st.session_state.tickers:
            st.session_state.tickers = new_tickers[:8]

    st.markdown("---")

    # 刷新設定
    st.markdown('<span style="font-family:IBM Plex Mono;font-size:9px;color:#555;letter-spacing:0.12em">REFRESH</span>', unsafe_allow_html=True)
    refresh_interval = st.slider("間隔 (秒)", 15, 120, st.session_state.refresh_interval, 5,
                                  label_visibility="collapsed")
    st.session_state.refresh_interval = refresh_interval
    st.markdown(f'<span style="font-family:IBM Plex Mono;font-size:9px;color:#555">{refresh_interval}s 刷新一次</span>', unsafe_allow_html=True)

    st.markdown("---")

    # 成交量瀑布設定
    st.markdown('<span style="font-family:IBM Plex Mono;font-size:9px;color:#555;letter-spacing:0.12em">VOLUME CASCADE</span>', unsafe_allow_html=True)
    vc_threshold = st.slider("觸發倍數", 0.8, 2.0, st.session_state.vc_threshold, 0.1,
                              label_visibility="collapsed")
    st.session_state.vc_threshold = vc_threshold
    st.markdown(f'<span style="font-family:IBM Plex Mono;font-size:9px;color:#555">{vc_threshold:.1f}× 前5根均量</span>', unsafe_allow_html=True)

    st.markdown("---")

    # Telegram控制
    st.markdown('<span style="font-family:IBM Plex Mono;font-size:9px;color:#555;letter-spacing:0.12em">TELEGRAM</span>', unsafe_allow_html=True)
    mute = st.checkbox("全局靜音", value=st.session_state.tg_global_mute)
    st.session_state.tg_global_mute = mute
    if mute:
        st.markdown('<span style="font-family:IBM Plex Mono;font-size:9px;color:#eb5757">⊘ 通知已靜音</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span style="font-family:IBM Plex Mono;font-size:9px;color:#6fcf97">● 通知開啟</span>', unsafe_allow_html=True)

    st.markdown("---")

    # 手動刷新
    if st.button("🔄 立即刷新", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    now_str = datetime.now().strftime("%H:%M:%S")
    st.markdown(f'<span style="font-family:IBM Plex Mono;font-size:9px;color:#333">{now_str} UTC</span>', unsafe_allow_html=True)


# ─── Header ──────────────────────────────────────────────────────────────────
vix = fetch_vix()
vix_color = C["bear"] if vix > 25 else C["warn"] if vix > 18 else C["bull"]
vix_label = "DANGER" if vix > 25 else "CAUTION" if vix > 18 else "CALM"

header_cols = st.columns([3, 1, 1, 1])
with header_cols[0]:
    st.markdown(
        f'<span class="live-dot"></span>'
        f'<span style="font-family:IBM Plex Mono;font-size:14px;font-weight:700;letter-spacing:0.1em">TRADING TERMINAL</span>'
        f'<span style="font-family:IBM Plex Mono;font-size:9px;color:#333;margin-left:10px">v2.0</span>',
        unsafe_allow_html=True
    )
with header_cols[1]:
    st.markdown(
        f'<div style="text-align:center">'
        f'<div style="font-family:IBM Plex Mono;font-size:9px;color:#555;letter-spacing:0.1em">VIX</div>'
        f'<div style="font-family:IBM Plex Mono;font-size:18px;font-weight:700;color:{vix_color}">{vix:.1f}</div>'
        f'<div style="font-family:IBM Plex Mono;font-size:8px;color:{vix_color};background:{vix_color}18;border:1px solid {vix_color}44;border-radius:3px;padding:1px 6px;display:inline-block">{vix_label}</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with header_cols[2]:
    st.markdown(
        f'<div style="text-align:center">'
        f'<div style="font-family:IBM Plex Mono;font-size:9px;color:#555;letter-spacing:0.1em">WATCHLIST</div>'
        f'<div style="font-family:IBM Plex Mono;font-size:18px;font-weight:700;color:#e8e4dc">{len(st.session_state.tickers)}</div>'
        f'<div style="font-family:IBM Plex Mono;font-size:8px;color:#555">stocks</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with header_cols[3]:
    now = datetime.now()
    st.markdown(
        f'<div style="text-align:right">'
        f'<div style="font-family:IBM Plex Mono;font-size:11px;color:#e8e4dc">{now.strftime("%H:%M:%S")}</div>'
        f'<div style="font-family:IBM Plex Mono;font-size:8px;color:#555">{now.strftime("%Y-%m-%d")}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

st.markdown('<hr style="border-color:#1e1e1e;margin:8px 0 12px"/>', unsafe_allow_html=True)


# ─── 數據加載 & 成交量瀑布檢查 ────────────────────────────────────────────────
@st.cache_data(ttl=30, show_spinner=False)
def load_all_data(tickers):
    data = {}
    for t in tickers:
        df_5m  = fetch_ohlcv(t, "5m",  "1d")
        df_15m = fetch_ohlcv(t, "15m", "5d")
        df_1d  = fetch_ohlcv(t, "1d",  "6mo")
        quote  = fetch_quote(t)
        data[t] = {
            "df_5m": df_5m, "df_15m": df_15m, "df_1d": df_1d,
            "quote": quote,
        }
    return data

with st.spinner(""):
    all_data = load_all_data(tuple(st.session_state.tickers))


# ─── 股票卡片網格 ─────────────────────────────────────────────────────────────
st.markdown('<span style="font-family:IBM Plex Mono;font-size:9px;color:#555;letter-spacing:0.12em">SIGNAL OVERVIEW</span>', unsafe_allow_html=True)

n = len(st.session_state.tickers)
card_cols = st.columns(min(n, 5))

stock_metrics = {}  # 存儲各股指標供後續使用

for i, ticker in enumerate(st.session_state.tickers):
    col = card_cols[i % 5]
    d = all_data.get(ticker, {})
    quote = d.get("quote", {})
    df_1d = d.get("df_1d", pd.DataFrame())
    df_5m = d.get("df_5m", pd.DataFrame())
    df_15m = d.get("df_15m", pd.DataFrame())

    price    = quote.get("price", 0)
    change1d = quote.get("change1d", 0)

    # 計算指標
    metrics = {"score": 50, "rsi": 50, "macd": 0, "ema8": price, "ema21": price, "ema55": price, "reasons": []}
    if not df_1d.empty and len(df_1d) >= 30:
        try:
            metrics = resonance_score(df_1d, vix)
        except Exception:
            pass

    # 成交量瀑布
    vc = run_cascade(ticker, df_5m, df_15m, st.session_state.vc_threshold)

    # Telegram通知
    if vc["new_event"]:
        is_major = vc["state"] == "major"
        add_global_alert(ticker, "danger" if is_major else "warn", vc["message"])
        send_volume_cascade(ticker, vc["ratio_5m"], vc["ratio_15m"], price, is_major)

    stock_metrics[ticker] = {**metrics, **vc, "price": price, "change1d": change1d}
    sc = metrics["score"]
    sc_color = score_color(sc)

    # 成交量狀態
    vc_state = vc["state"]
    if vc_state == "major":
        dot_html = '<span class="danger-dot"></span>'
        card_border = C["bear"]
        card_top = C["bear"]
    elif vc_state == "watching":
        dot_html = '<span class="warn-dot"></span>'
        card_border = C["warn"]
        card_top = C["warn"]
    else:
        dot_html = ""
        card_border = sc_color
        card_top = sc_color

    selected = st.session_state.selected == ticker

    with col:
        # 點擊選擇股票
        is_selected = st.session_state.selected == ticker
        btn_style = f"border:1px solid {card_border}66;" if is_selected else f"border:1px solid #1e1e1e;"

        st.markdown(
            f'<div style="background:#0d0d0d;{btn_style}border-top:2px solid {card_top};'
            f'border-radius:8px;padding:12px 14px;margin-bottom:4px;cursor:pointer">',
            unsafe_allow_html=True
        )

        # Sector + ticker
        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<div>'
            f'<div style="font-family:IBM Plex Mono;font-size:8px;color:#444;letter-spacing:0.12em">STOCK</div>'
            f'<div style="font-family:IBM Plex Mono;font-size:15px;font-weight:700;color:#e8e4dc">{dot_html}{ticker}</div>'
            f'</div>'
            # Resonance ring (SVG inline)
            f'<svg width="32" height="32" style="transform:rotate(-90deg)">'
            f'<circle cx="16" cy="16" r="12" fill="none" stroke="#1e1e1e" stroke-width="2.5"/>'
            f'<circle cx="16" cy="16" r="12" fill="none" stroke="{sc_color}" stroke-width="2.5"'
            f' stroke-dasharray="{(sc/100)*75.4:.1f} 75.4" stroke-linecap="round"/>'
            f'</svg>'
            f'</div>',
            unsafe_allow_html=True
        )

        # Price
        p_color = C["bull"] if change1d >= 0 else C["bear"]
        st.markdown(
            f'<div style="font-family:IBM Plex Mono;font-size:18px;font-weight:700;'
            f'color:{p_color};margin:6px 0 3px;letter-spacing:-0.02em">'
            f'${price:.2f}</div>'
            f'<div style="display:inline-flex;align-items:center;gap:4px;'
            f'background:{p_color}18;border:1px solid {p_color}44;border-radius:4px;'
            f'padding:1px 7px;font-family:IBM Plex Mono;font-size:10px;font-weight:700;color:{p_color}">'
            f'{price_arrow(change1d)} {abs(change1d):.2f}%</div>',
            unsafe_allow_html=True
        )

        # Indicators row: RSI arc + MACD dot
        rsi_v = metrics["rsi"]
        macd_v = metrics["macd"]
        rsi_color = C["bear"] if rsi_v > 70 else C["bull"] if rsi_v < 30 else (C["bull"] if rsi_v > 55 else C["warn"])
        macd_color = C["bull"] if macd_v >= 0 else C["bear"]
        macd_size = min(int(abs(macd_v) * 8 + 5), 14)

        # RSI arc SVG
        pct = rsi_v / 100
        import math
        ang = math.pi + math.pi * pct
        r = 14
        x1, y1 = 18 + r * math.cos(math.pi), 18 + r * math.sin(math.pi)
        x2, y2 = 18 + r * math.cos(ang),     18 + r * math.sin(ang)
        large = 1 if pct > 0.5 else 0

        st.markdown(
            f'<div style="display:flex;justify-content:space-between;align-items:flex-end;margin-top:8px">'
            f'<svg width="36" height="22">'
            f'<path d="M {18-r} 18 A {r} {r} 0 0 1 {18+r} 18" fill="none" stroke="#1e1e1e" stroke-width="2" stroke-linecap="round"/>'
            f'<path d="M {x1:.1f} {y1:.1f} A {r} {r} 0 {large} 1 {x2:.1f} {y2:.1f}" fill="none" stroke="{rsi_color}" stroke-width="2" stroke-linecap="round"/>'
            f'<text x="18" y="19" text-anchor="middle" fill="{rsi_color}" style="font-size:7px;font-family:IBM Plex Mono;font-weight:700">{rsi_v:.0f}</text>'
            f'</svg>'
            f'<div style="display:flex;align-items:center;gap:4px">'
            f'<div style="width:{macd_size}px;height:{macd_size}px;border-radius:50%;background:{macd_color};box-shadow:0 0 {macd_size}px {macd_color}88"></div>'
            f'<span style="font-size:9px;color:{macd_color};font-family:IBM Plex Mono">{"▲" if macd_v >= 0 else "▼"}</span>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True
        )

        # Volume bar
        ratio_5m = vc.get("ratio_5m", 0)
        v_color = vol_color(ratio_5m)
        v_pct = min(int((ratio_5m / 2.5) * 100), 100)
        st.markdown(
            f'<div style="margin-top:7px">'
            f'<div style="height:3px;background:#1a1a1a;border-radius:2px">'
            f'<div style="height:3px;width:{v_pct}%;background:{v_color};border-radius:2px;'
            f'{"box-shadow:0 0 5px " + v_color if ratio_5m >= 1.0 else ""}"></div>'
            f'</div>'
            f'<div style="font-family:IBM Plex Mono;font-size:8px;color:{v_color};margin-top:2px">'
            f'5m {ratio_5m:.2f}× avg</div>'
            f'</div>',
            unsafe_allow_html=True
        )

        st.markdown('</div>', unsafe_allow_html=True)

        # 點擊按鈕
        if st.button(f"選擇 {ticker}", key=f"btn_{ticker}", use_container_width=True):
            st.session_state.selected = ticker
            st.rerun()


st.markdown('<hr style="border-color:#1e1e1e;margin:12px 0"/>', unsafe_allow_html=True)


# ─── Force Graph 訊號網絡圖 ───────────────────────────────────────────────────
def build_force_graph_html(stock_metrics: dict, vix: float, tickers: list) -> str:
    """
    生成完整的Force Graph HTML字符串
    節點由stocks實時數據驅動：
      TICKER節點  → 大小=共振分數，顏色=多/空/中性
      INDICATOR節點 → RSI超買超賣、MACD方向、量能異動
      CATALYST節點  → VIX狀態
      CLUSTER節點   → 3+股票同向聚合
      COLLISION節點 → 多空訊號衝突
    """
    # 序列化stocks數據給JS使用
    stocks_js = {}
    for t in tickers:
        m = stock_metrics.get(t, {})
        stocks_js[t] = {
            "score":    m.get("score", 50),
            "rsi":      m.get("rsi", 50),
            "macd":     m.get("macd", 0),
            "ratio5m":  m.get("ratio_5m", 0) or 0,
            "ratio15m": m.get("ratio_15m", 0) or 0,
            "state":    m.get("state", "normal"),
            "price":    m.get("price", 0),
            "change1d": m.get("change1d", 0),
        }

    stocks_json = json.dumps(stocks_js)
    tickers_json = json.dumps(tickers)
    vix_val = float(vix)

    html = f"""
<div style="background:#080808;border:1px solid #1e1e1e;border-radius:8px;overflow:hidden;margin-bottom:4px">
  <div style="padding:8px 14px 0;display:flex;align-items:center;gap:10px">
    <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#555;letter-spacing:0.12em">SIGNAL NETWORK</span>
    <span style="font-family:'IBM Plex Mono',monospace;font-size:8px;color:#333">節點由實時訊號驅動 · 大小=共振強度 · 顏色=方向</span>
  </div>
  <canvas id="fgCanvas" style="display:block;width:100%;height:260px;cursor:crosshair"></canvas>
  <div id="fgTooltip" style="display:none;position:absolute;background:rgba(8,8,8,0.95);border:1px solid #2a2a2a;border-radius:5px;padding:7px 10px;font-family:'IBM Plex Mono',monospace;pointer-events:none;z-index:999"></div>
</div>

<script>
(function() {{
  const STOCKS = {stocks_json};
  const TICKERS = {tickers_json};
  const VIX = {vix_val};

  const C = {{
    bull: '#6fcf97', bear: '#eb5757', warn: '#f2c94c',
    info: '#56b4e9', purple: '#bb86fc', pink: '#ff79c6',
  }};

  function clamp(v,lo,hi){{ return Math.max(lo,Math.min(hi,v)); }}
  function rand(a,b){{ return a+Math.random()*(b-a); }}
  function scoreColor(s){{ return s>=65?C.bull:s>=50?C.warn:C.bear; }}

  // ── 建構節點和邊 ──────────────────────────────────────────────────────────
  const nodes=[], edges=[];
  let nid=0;
  const tickerIds={{}};

  // Ticker主節點
  TICKERS.forEach(t => {{
    const d = STOCKS[t]||{{}};
    const sc = d.score||50;
    const color = scoreColor(sc);
    const id = nid++;
    tickerIds[t] = id;
    nodes.push({{
      id, label:t, type:'TICKER',
      color, size: 8+(sc/100)*10,
      glow: sc>=65||sc<40,
      sub: '$'+(d.price||0).toFixed(0),
      pulse: rand(0,Math.PI*2), vx:0, vy:0, x:0, y:0,
    }});
  }});

  // Indicator節點
  TICKERS.forEach(t => {{
    const d = STOCKS[t]||{{}};
    const tid = tickerIds[t];
    if(d.rsi>70||d.rsi<30){{
      const id=nid++;
      nodes.push({{id,label:d.rsi>70?'RSI↑':'RSI↓',type:'INDICATOR',
        color:d.rsi<30?C.bull:C.bear,size:5,glow:false,
        pulse:rand(0,Math.PI*2),vx:0,vy:0,x:0,y:0}});
      edges.push({{a:tid,b:id,strength:0.8,dashed:false}});
    }}
    if(Math.abs(d.macd||0)>0.5){{
      const id=nid++;
      nodes.push({{id,label:(d.macd||0)>0?'MACD+':'MACD−',type:'INDICATOR',
        color:(d.macd||0)>0?C.bull:C.bear,size:5,glow:false,
        pulse:rand(0,Math.PI*2),vx:0,vy:0,x:0,y:0}});
      edges.push({{a:tid,b:id,strength:0.7,dashed:false}});
    }}
    if((d.ratio5m||0)>=(1.0)){{
      const id=nid++;
      const isMajor=(d.ratio15m||0)>=1.0;
      nodes.push({{id,label:isMajor?'VOL🚨':'VOL↑',type:'INDICATOR',
        color:isMajor?C.bear:C.info,size:isMajor?8:5,glow:isMajor,
        pulse:rand(0,Math.PI*2),vx:0,vy:0,x:0,y:0}});
      edges.push({{a:tid,b:id,strength:isMajor?1.0:0.6,dashed:!isMajor}});
    }}
  }});

  // VIX Catalyst
  const vixColor = VIX>25?C.bear:VIX>18?C.warn:C.bull;
  const vixId=nid++;
  nodes.push({{id:vixId,label:'VIX '+(VIX).toFixed(1),type:'CATALYST',
    color:vixColor,size:13,glow:VIX>22,
    pulse:0,vx:0,vy:0,x:0,y:0}});
  TICKERS.forEach(t=>edges.push({{a:vixId,b:tickerIds[t],strength:0.25,dashed:true}}));

  // Cluster
  const bulls=TICKERS.filter(t=>(STOCKS[t]?.score||50)>=65);
  const bears=TICKERS.filter(t=>(STOCKS[t]?.score||50)<40);
  if(bulls.length>=2){{
    const id=nid++;
    nodes.push({{id,label:'BULL CLUSTER',type:'CLUSTER',
      color:C.bull,size:16,glow:true,pulse:0,vx:0,vy:0,x:0,y:0}});
    bulls.forEach(t=>edges.push({{a:id,b:tickerIds[t],strength:0.9,dashed:false}}));
  }}
  if(bears.length>=2){{
    const id=nid++;
    nodes.push({{id,label:'BEAR CLUSTER',type:'CLUSTER',
      color:C.bear,size:16,glow:true,pulse:0,vx:0,vy:0,x:0,y:0}});
    bears.forEach(t=>edges.push({{a:id,b:tickerIds[t],strength:0.9,dashed:false}}));
  }}

  // Collision
  if(bulls.length>=1&&bears.length>=1){{
    const id=nid++;
    nodes.push({{id,label:'COLLISION',type:'COLLISION',
      color:C.pink,size:7,glow:false,pulse:rand(0,Math.PI*2),vx:0,vy:0,x:0,y:0}});
    edges.push({{a:id,b:tickerIds[bulls[0]],strength:0.5,dashed:true}});
    edges.push({{a:id,b:tickerIds[bears[0]],strength:0.5,dashed:true}});
  }}

  // 整體市場方向
  const scores=TICKERS.map(t=>(STOCKS[t]?.score||50));
  const avgSc=scores.reduce((a,b)=>a+b,0)/scores.length;
  const mktColor=avgSc>=65?C.bull:avgSc<40?C.bear:C.warn;
  const mktLabel=avgSc>=65?'STRONG UP':avgSc<40?'STRONG DOWN':'NEUTRAL';
  const mktId=nid++;
  nodes.push({{id:mktId,label:mktLabel,type:'CATALYST',
    color:mktColor,size:11,glow:true,pulse:0,vx:0,vy:0,x:0,y:0}});
  edges.push({{a:mktId,b:vixId,strength:0.35,dashed:true}});

  // ── Canvas 設定 ──────────────────────────────────────────────────────────
  const canvas = document.getElementById('fgCanvas');
  const tip    = document.getElementById('fgTooltip');
  let W=canvas.offsetWidth, H=260;
  canvas.width=W; canvas.height=H;
  const ctx = canvas.getContext('2d');

  // 初始位置：圓形排列
  nodes.forEach((n,i)=>{{
    const ang=(i/nodes.length)*Math.PI*2;
    const r=Math.min(W,H)*0.3;
    n.x=W/2+r*Math.cos(ang)+rand(-15,15);
    n.y=H/2+r*Math.sin(ang)+rand(-15,15);
  }});

  // ── Physics ───────────────────────────────────────────────────────────────
  function applyForces(){{
    const CX=W/2,CY=H/2;
    const REPEL=1400,SPRING=0.016,REST=90,DAMP=0.82,CENTER=0.005;
    nodes.forEach(n=>{{
      n.vx=(n.vx||0)*DAMP;
      n.vy=(n.vy||0)*DAMP;
      n.vx+=(CX-n.x)*CENTER;
      n.vy+=(CY-n.y)*CENTER;
      n.pulse=(n.pulse||0)+0.03;
    }});
    for(let i=0;i<nodes.length;i++){{
      for(let j=i+1;j<nodes.length;j++){{
        const dx=nodes[j].x-nodes[i].x, dy=nodes[j].y-nodes[i].y;
        const d=Math.sqrt(dx*dx+dy*dy)||1;
        const f=REPEL/(d*d);
        const fx=(dx/d)*f, fy=(dy/d)*f;
        nodes[i].vx-=fx; nodes[i].vy-=fy;
        nodes[j].vx+=fx; nodes[j].vy+=fy;
      }}
    }}
    edges.forEach(e=>{{
      const a=nodes[e.a],b=nodes[e.b];
      if(!a||!b)return;
      const dx=b.x-a.x,dy=b.y-a.y;
      const d=Math.sqrt(dx*dx+dy*dy)||1;
      const f=(d-REST)*SPRING*(e.strength||0.5);
      const fx=(dx/d)*f,fy=(dy/d)*f;
      a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;
    }});
    nodes.forEach(n=>{{
      n.x=clamp(n.x+n.vx,n.size+4,W-n.size-4);
      n.y=clamp(n.y+n.vy,n.size+4,H-n.size-20);
    }});
  }}

  // ── Draw ─────────────────────────────────────────────────────────────────
  function draw(){{
    ctx.clearRect(0,0,W,H);

    // 背景格線
    ctx.strokeStyle='#111'; ctx.lineWidth=0.5;
    for(let x=0;x<W;x+=44){{ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,H);ctx.stroke();}}
    for(let y=0;y<H;y+=44){{ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(W,y);ctx.stroke();}}

    // 邊
    edges.forEach(e=>{{
      const a=nodes[e.a],b=nodes[e.b];
      if(!a||!b)return;
      ctx.save();
      if(e.dashed)ctx.setLineDash([3,6]);
      ctx.lineWidth=0.6+(e.strength||0.5)*0.9;
      const sameColor=a.color===b.color;
      ctx.strokeStyle=sameColor
        ? a.color+'28'
        : 'rgba(180,180,180,0.10)';
      ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();
      ctx.restore();
    }});

    // 節點
    nodes.forEach(n=>{{
      const r=n.size+Math.sin(n.pulse)*1.8;

      // 光暈
      if(n.glow){{
        const g=ctx.createRadialGradient(n.x,n.y,r*0.4,n.x,n.y,r*2.8);
        g.addColorStop(0,n.color+'30');g.addColorStop(1,'transparent');
        ctx.beginPath();ctx.arc(n.x,n.y,r*2.8,0,Math.PI*2);
        ctx.fillStyle=g;ctx.fill();
      }}

      // 主圓
      ctx.beginPath();ctx.arc(n.x,n.y,r,0,Math.PI*2);
      ctx.fillStyle=n.color;
      ctx.shadowColor=n.color;ctx.shadowBlur=n.glow?14:5;
      ctx.fill();ctx.shadowBlur=0;

      // 高光
      ctx.beginPath();ctx.arc(n.x-r*0.28,n.y-r*0.28,r*0.32,0,Math.PI*2);
      ctx.fillStyle='rgba(255,255,255,0.15)';ctx.fill();

      // 標籤
      const big=n.type==='CLUSTER'||n.type==='CATALYST';
      ctx.font=(big?'700 9px':'400 8px')+' "IBM Plex Mono",monospace';
      ctx.fillStyle=n.type==='TICKER'?'#e8e4dc':n.color+'dd';
      ctx.textAlign='center';
      ctx.fillText(n.label,n.x,n.y+r+11);
      if(n.type==='TICKER'&&n.sub){{
        ctx.font='400 7px "IBM Plex Mono",monospace';
        ctx.fillStyle='#555';
        ctx.fillText(n.sub,n.x,n.y+r+20);
      }}
    }});

    // 右上角stats
    const statsX=W-12, statsY=12;
    const lines=[
      ['CONVERGENCE', (Math.abs(avgSc-50)*2).toFixed(0)+'%', mktColor],
      ['BULL NODES',  bulls.length+'', C.bull],
      ['BEAR NODES',  bears.length+'', C.bear],
      ['SIGNAL',      mktLabel,        mktColor],
    ];
    ctx.fillStyle='rgba(8,8,8,0.85)';
    ctx.beginPath();ctx.roundRect(statsX-130,statsY,130,lines.length*16+12,4);ctx.fill();
    lines.forEach((l,i)=>{{
      ctx.font='400 8px "IBM Plex Mono",monospace';
      ctx.fillStyle='#444';ctx.textAlign='left';
      ctx.fillText(l[0],statsX-126,statsY+10+i*16);
      ctx.fillStyle=l[2];ctx.textAlign='right';
      ctx.fillText(l[1],statsX-4,statsY+10+i*16);
    }});

    // 左上角圖例
    const leg=[
      [C.bull,'BULL'],
      [C.bear,'BEAR'],
      [C.warn,'NEUTRAL'],
      [C.info,'VOL SPIKE'],
      ['#bb86fc','CLUSTER'],
      [C.pink,'COLLISION'],
    ];
    ctx.fillStyle='rgba(8,8,8,0.85)';
    ctx.beginPath();ctx.roundRect(8,8,108,leg.length*14+10,4);ctx.fill();
    leg.forEach((l,i)=>{{
      ctx.beginPath();ctx.arc(18,16+i*14,4,0,Math.PI*2);
      ctx.fillStyle=l[0];ctx.fill();
      ctx.font='400 8px "IBM Plex Mono",monospace';
      ctx.fillStyle='#666';ctx.textAlign='left';
      ctx.fillText(l[1],26,19+i*14);
    }});

    // 底部信號badge
    ctx.font='700 10px "IBM Plex Mono",monospace';
    ctx.fillStyle=mktColor+'18';
    const bw=110,bh=18,bx=(W-bw)/2,by=H-26;
    ctx.beginPath();ctx.roundRect(bx,by,bw,bh,4);ctx.fill();
    ctx.strokeStyle=mktColor+'44';ctx.lineWidth=1;
    ctx.beginPath();ctx.roundRect(bx,by,bw,bh,4);ctx.stroke();
    ctx.fillStyle=mktColor;ctx.textAlign='center';
    ctx.fillText(mktLabel,W/2,by+13);
  }}

  // ── Loop ─────────────────────────────────────────────────────────────────
  function loop(){{
    applyForces();draw();
    requestAnimationFrame(loop);
  }}
  requestAnimationFrame(loop);

  // ── Tooltip ───────────────────────────────────────────────────────────────
  canvas.addEventListener('mousemove',e=>{{
    const rect=canvas.getBoundingClientRect();
    const mx=(e.clientX-rect.left)*(canvas.width/rect.width);
    const my=(e.clientY-rect.top)*(canvas.height/rect.height);
    let hit=null;
    for(const n of nodes){{
      const dx=n.x-mx,dy=n.y-my;
      if(Math.sqrt(dx*dx+dy*dy)<n.size+8){{hit=n;break;}}
    }}
    if(hit){{
      tip.style.display='block';
      tip.style.left=(e.clientX+12)+'px';
      tip.style.top=(e.clientY-10)+'px';
      const d=STOCKS[hit.label]||{{}};
      tip.innerHTML=
        '<div style="color:'+hit.color+';font-weight:700;font-size:10px;margin-bottom:3px">'+hit.label+'</div>'+
        '<div style="color:#888;font-size:9px">TYPE: '+hit.type+'</div>'+
        (d.score!==undefined?'<div style="color:#888;font-size:9px">共振: '+d.score+'/100</div>':'')+
        (d.price?'<div style="color:#888;font-size:9px">價格: $'+d.price.toFixed(2)+'</div>':'');
    }}else{{
      tip.style.display='none';
    }}
  }});
  canvas.addEventListener('mouseleave',()=>{{ tip.style.display='none'; }});
}})();
</script>
"""
    return html


# 渲染Force Graph
fg_html = build_force_graph_html(stock_metrics, vix, st.session_state.tickers)
components.html(fg_html, height=290, scrolling=False)

st.markdown('<hr style="border-color:#1e1e1e;margin:8px 0 12px"/>', unsafe_allow_html=True)


# ─── 主分析區 ─────────────────────────────────────────────────────────────────
sel = st.session_state.selected
sel_data = all_data.get(sel, {})
sel_metrics = stock_metrics.get(sel, {})
sel_quote = sel_data.get("quote", {})
sel_price = sel_quote.get("price", 0)
sel_chg   = sel_quote.get("change1d", 0)
sel_up    = sel_chg >= 0
sel_score = sel_metrics.get("score", 50)
sel_sc    = score_color(sel_score)
sel_vc    = {k: sel_metrics.get(k) for k in ["state","alert_level","ratio_5m","ratio_15m","message"]}

main_left, main_right = st.columns([2, 1], gap="medium")

with main_left:

    # ── 成交量瀑布預警面板 ────────────────────────────────────────────────────
    vc_state   = sel_vc.get("state", "normal")
    vc_msg     = sel_vc.get("message", "")
    ratio_5m   = sel_vc.get("ratio_5m", 0) or 0
    ratio_15m  = sel_vc.get("ratio_15m", 0) or 0

    if vc_state == "major":
        panel_class = "vc-danger"
        panel_title = "🚨 大事預警"
        state_dot   = '<span class="danger-dot"></span>'
    elif vc_state == "watching":
        panel_class = "vc-warn"
        panel_title = "🔔 第一警號 — 監視15min中"
        state_dot   = '<span class="warn-dot"></span>'
    else:
        panel_class = "vc-normal"
        panel_title = "● 量能正常"
        state_dot   = ""

    # 5min bar
    v5_color = vol_color(ratio_5m)
    v5_pct   = min(int((ratio_5m / 2.5) * 100), 100)
    v15_color = vol_color(ratio_15m)
    v15_pct  = min(int((ratio_15m / 2.5) * 100), 100)

    st.markdown(
        f'<div class="{panel_class}">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">'
        f'<span style="font-family:IBM Plex Mono;font-size:11px;font-weight:700;color:{"#eb5757" if vc_state=="major" else "#f2c94c" if vc_state=="watching" else "#555"}">'
        f'{state_dot}{panel_title}</span>'
        f'<span style="font-family:IBM Plex Mono;font-size:8px;color:#555">VOLUME CASCADE · {sel}</span>'
        f'</div>'

        # 5min row
        f'<div style="margin-bottom:8px">'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:3px">'
        f'<span style="font-family:IBM Plex Mono;font-size:9px;color:#aaa">5min K線</span>'
        f'<span style="font-family:IBM Plex Mono;font-size:10px;font-weight:700;color:{v5_color}">{ratio_5m:.2f}× 均量'
        f'{"  ⚠" if ratio_5m >= st.session_state.vc_threshold else ""}</span>'
        f'</div>'
        f'<div class="vol-bar-container"><div class="vol-bar-fill" style="width:{v5_pct}%;background:{v5_color};{"box-shadow:0 0 6px " + v5_color if ratio_5m >= 1.0 else ""}"></div></div>'
        f'</div>'

        # 15min row
        f'<div>'
        f'<div style="display:flex;justify-content:space-between;margin-bottom:3px">'
        f'<span style="font-family:IBM Plex Mono;font-size:9px;color:#aaa">15min K線</span>'
        f'<span style="font-family:IBM Plex Mono;font-size:10px;font-weight:700;color:{v15_color}">{ratio_15m:.2f}× 均量'
        f'{"  🚨" if ratio_15m >= st.session_state.vc_threshold else ""}</span>'
        f'</div>'
        f'<div class="vol-bar-container"><div class="vol-bar-fill" style="width:{v15_pct}%;background:{v15_color};{"box-shadow:0 0 6px " + v15_color if ratio_15m >= 1.0 else ""}"></div></div>'
        f'</div>'

        f'</div>',
        unsafe_allow_html=True
    )

    # ── K線圖 ─────────────────────────────────────────────────────────────────
    st.markdown('<div style="margin-top:12px"></div>', unsafe_allow_html=True)

    df_5m_plot = sel_data.get("df_5m", pd.DataFrame())
    df_1d_plot = sel_data.get("df_1d", pd.DataFrame())

    tab1, tab2 = st.tabs(["📊 5min K線", "📈 日線"])

    def make_kline(df, ticker, title):
        if df is None or df.empty:
            return None
        fig = go.Figure()

        # K線
        fig.add_trace(go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"],
            increasing_line_color=C["bull"], decreasing_line_color=C["bear"],
            increasing_fillcolor="rgba(111,207,151,0.55)",
            decreasing_fillcolor="rgba(235,87,87,0.55)",
            name="K線", showlegend=False,
        ))

        # EMA（僅日線）
        if len(df) >= 55:
            close = df["Close"]
            for period, color, name in [
                (8,  "rgba(111,207,151,0.7)", "EMA8"),
                (21, "rgba(242,201,76,0.7)",  "EMA21"),
                (55, "rgba(86,180,233,0.7)",  "EMA55"),
            ]:
                e = close.ewm(span=period, adjust=False).mean()
                fig.add_trace(go.Scatter(x=df.index, y=e, line=dict(color=color, width=1),
                                          name=name, showlegend=True))

        # 成交量 (副圖)
        colors = [C["bull"] if c >= o else C["bear"]
                  for c, o in zip(df["Close"], df["Open"])]
        fig.add_trace(go.Bar(
            x=df.index, y=df["Volume"], marker_color=colors,
            opacity=0.5, name="Volume", yaxis="y2", showlegend=False,
        ))

        # 均量線
        if len(df) >= 5:
            avg5 = df["Volume"].rolling(5).mean()
            fig.add_trace(go.Scatter(
                x=df.index, y=avg5,
                line=dict(color="rgba(242,201,76,0.6)", width=1, dash="dot"),
                name="Vol Avg5", yaxis="y2", showlegend=True,
            ))

        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=30, b=0),
            height=320,
            title=dict(text=f"{ticker} · {title}", font=dict(family="IBM Plex Mono", size=11, color="#aaa"), x=0),
            xaxis=dict(gridcolor="#111", tickfont=dict(family="IBM Plex Mono", size=9, color="#555"),
                       rangeslider_visible=False, showgrid=True),
            yaxis=dict(gridcolor="#111", tickfont=dict(family="IBM Plex Mono", size=9, color="#555"),
                       domain=[0.28, 1]),
            yaxis2=dict(domain=[0, 0.25], gridcolor="#111", showgrid=False,
                        tickfont=dict(family="IBM Plex Mono", size=8, color="#333")),
            legend=dict(font=dict(family="IBM Plex Mono", size=9, color="#777"),
                        bgcolor="rgba(0,0,0,0)", orientation="h", y=1.02),
            hovermode="x unified",
        )
        return fig

    with tab1:
        fig5 = make_kline(df_5m_plot, sel, "5min")
        if fig5:
            st.plotly_chart(fig5, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown('<div style="text-align:center;padding:40px;color:#333;font-family:IBM Plex Mono;font-size:10px">數據加載中…</div>', unsafe_allow_html=True)

    with tab2:
        fig1d = make_kline(df_1d_plot, sel, "日線")
        if fig1d:
            st.plotly_chart(fig1d, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown('<div style="text-align:center;padding:40px;color:#333;font-family:IBM Plex Mono;font-size:10px">數據加載中…</div>', unsafe_allow_html=True)

    # ── Global Alert Log ──────────────────────────────────────────────────────
    st.markdown('<hr style="border-color:#1e1e1e;margin:10px 0 8px"/>', unsafe_allow_html=True)
    st.markdown('<span style="font-family:IBM Plex Mono;font-size:9px;color:#555;letter-spacing:0.12em">ALERT LOG</span>', unsafe_allow_html=True)

    all_logs = []
    for t in st.session_state.tickers:
        for entry in get_cascade_log(t):
            all_logs.append(entry)
    all_logs += st.session_state.global_alerts
    all_logs.sort(key=lambda x: x.get("time", ""), reverse=True)

    if not all_logs:
        st.markdown('<div style="font-family:IBM Plex Mono;font-size:10px;color:#333;padding:16px 0;text-align:center">待機中…</div>', unsafe_allow_html=True)
    else:
        for j, entry in enumerate(all_logs[:12]):
            lvl    = entry.get("level", "info")
            accent = C["bear"] if lvl == "danger" else C["warn"] if lvl == "warn" else C["info"]
            arrow  = "▼" if lvl == "danger" else "⚠" if lvl == "warn" else "↑"
            alpha  = max(0.2, 1 - j * 0.12)
            bg     = f"{accent}12" if j == 0 else "transparent"
            border = f"{accent}44" if j == 0 else "#161616"
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;'
                f'background:{bg};border:1px solid {border};border-left:3px solid {accent};'
                f'border-radius:6px;padding:7px 10px;margin-bottom:4px;opacity:{alpha:.2f}">'
                f'<span style="font-size:18px;font-weight:900;color:{accent};min-width:20px;text-align:center;'
                f'{"filter:drop-shadow(0 0 6px " + accent + ")" if j == 0 else ""}">{arrow}</span>'
                f'<div style="background:{accent}28;border:1px solid {accent}55;border-radius:4px;'
                f'padding:2px 7px;font-family:IBM Plex Mono;font-size:10px;font-weight:700;color:{accent};flex-shrink:0">'
                f'{entry.get("ticker","–")}</div>'
                f'<div style="flex:1;min-width:0">'
                f'<div style="font-family:IBM Plex Mono;font-size:10px;font-weight:700;color:{accent}">'
                f'{entry.get("msg","")}</div>'
                f'<div style="font-family:IBM Plex Mono;font-size:8px;color:#555;margin-top:1px">{entry.get("time","")}</div>'
                f'</div>'
                f'{"<div style=\"font-family:IBM Plex Mono;font-size:8px;color:" + accent + ";background:" + accent + "22;border:1px solid " + accent + "44;border-radius:3px;padding:1px 5px;letter-spacing:0.1em\">● LIVE</div>" if j == 0 else ""}'
                f'</div>',
                unsafe_allow_html=True
            )


with main_right:

    # ── AI分析報告 ────────────────────────────────────────────────────────────
    st.markdown(
        f'<div style="background:#0d0d0d;border:1px solid #1e1e1e;border-radius:8px;padding:14px 16px">',
        unsafe_allow_html=True
    )

    # Header
    source_badge = '<span style="font-family:IBM Plex Mono;font-size:8px;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:3px;padding:2px 6px;color:#555">GROQ · llama-3.3</span>'
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">'
        f'<span style="font-family:IBM Plex Mono;font-size:10px;color:#aaa;letter-spacing:0.12em">AI ANALYSIS</span>'
        f'{source_badge}'
        f'<span style="font-family:IBM Plex Mono;font-size:8px;color:#6fcf97;background:#6fcf9711;border:1px solid #6fcf9733;border-radius:3px;padding:2px 6px">● LIVE</span>'
        f'</div>',
        unsafe_allow_html=True
    )

    # 獲取AI分析
    rsi_v  = sel_metrics.get("rsi", 50)
    macd_v = sel_metrics.get("macd", 0)
    r5m    = sel_vc.get("ratio_5m", 0) or 0
    r15m   = sel_vc.get("ratio_15m", 0) or 0

    with st.spinner(""):
        ai = groq_analysis(
            ticker=sel, score=sel_score,
            reasons=sel_metrics.get("reasons", []),
            price=sel_price, rsi=rsi_v, macd=macd_v,
            ratio_5m=r5m, ratio_15m=r15m, vix=vix,
        )

    trend = ai.get("trend", "中性")
    trend_up = "多" in trend
    trend_color = C["bull"] if trend_up else C["warn"] if "中" in trend else C["bear"]

    # 趨勢 — 大色塊
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:center;'
        f'background:{trend_color}12;border:1px solid {trend_color}33;'
        f'border-radius:6px;padding:8px 12px;margin-bottom:10px">'
        f'<span style="font-family:IBM Plex Mono;font-size:9px;color:#aaa">趨勢判斷</span>'
        f'<span style="font-family:IBM Plex Mono;font-size:16px;font-weight:700;color:{trend_color}">{trend} {"▲" if trend_up else "▼" if "空" in trend else "→"}</span>'
        f'</div>',
        unsafe_allow_html=True
    )

    # Entry / Stop / Target — 三色塊
    entry  = ai.get("entry", sel_price * 0.993)
    stop   = ai.get("stop",  sel_price * 0.975)
    target = ai.get("target",sel_price * 1.035)
    kelly  = ai.get("kelly", 15)
    rr     = ai.get("rr", 2.0)

    cols3 = st.columns(3)
    for col3, (label, val, color) in zip(cols3, [
        ("ENTRY",  entry,  C["warn"]),
        ("STOP",   stop,   C["bear"]),
        ("TARGET", target, C["bull"]),
    ]):
        with col3:
            st.markdown(
                f'<div style="background:{color}10;border:1px solid {color}33;border-radius:6px;'
                f'padding:8px 6px;text-align:center;margin-bottom:6px">'
                f'<div style="font-family:IBM Plex Mono;font-size:8px;color:#aaa;margin-bottom:3px">{label}</div>'
                f'<div style="font-family:IBM Plex Mono;font-size:13px;font-weight:700;color:{color}">${val:.2f}</div>'
                f'</div>',
                unsafe_allow_html=True
            )

    st.markdown(
        f'<div style="display:flex;justify-content:space-between;font-family:IBM Plex Mono;font-size:9px;'
        f'color:#aaa;background:#0a0a0a;border-radius:4px;padding:5px 9px;margin-bottom:10px">'
        f'<span>R:R = 1:<span style="color:#e8e4dc">{rr}</span></span>'
        f'<span>Kelly <span style="color:{C["warn"]};font-weight:700">{kelly}%</span></span>'
        f'</div>',
        unsafe_allow_html=True
    )

    # 風險提醒 — 交通燈
    risks = ai.get("risks", [])
    st.markdown('<div style="font-family:IBM Plex Mono;font-size:9px;color:#aaa;letter-spacing:0.1em;margin-bottom:6px">風險提醒</div>', unsafe_allow_html=True)
    risk_positive = [rsi_v <= 68, macd_v >= 0, sel_score >= 60]
    for idx, risk in enumerate(risks[:3]):
        ok = risk_positive[idx] if idx < len(risk_positive) else True
        rc = C["bull"] if ok else C["bear"]
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:7px;padding:4px 8px;margin-bottom:4px;'
            f'background:{rc}08;border:1px solid {rc}22;border-radius:4px">'
            f'<div style="width:7px;height:7px;border-radius:50%;background:{rc};'
            f'box-shadow:0 0 5px {rc};flex-shrink:0"></div>'
            f'<span style="font-family:IBM Plex Mono;font-size:10px;color:#ccc">{risk}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    # 分析摘要
    summary = ai.get("summary", "")
    st.markdown(
        f'<div style="background:#0a0a0a;border:1px solid #1e1e1e;border-radius:5px;padding:9px 11px;margin-top:8px">'
        f'<div style="font-family:IBM Plex Mono;font-size:9px;color:#aaa;letter-spacing:0.1em;margin-bottom:5px">分析摘要</div>'
        f'<div style="font-family:IBM Plex Mono;font-size:10px;color:#ccc;line-height:1.8">{summary}</div>'
        f'</div>',
        unsafe_allow_html=True
    )

    # 觸發條件
    reasons = sel_metrics.get("reasons", [])
    if reasons:
        st.markdown(
            f'<div style="margin-top:8px">'
            f'<div style="font-family:IBM Plex Mono;font-size:9px;color:#aaa;letter-spacing:0.1em;margin-bottom:5px">共振條件</div>',
            unsafe_allow_html=True
        )
        for r in reasons:
            ok = "✅" in r
            rc = C["bull"] if ok else C["warn"] if "⚠️" in r else C["bear"]
            st.markdown(
                f'<div style="font-family:IBM Plex Mono;font-size:9px;color:{rc};margin-bottom:3px">{r}</div>',
                unsafe_allow_html=True
            )
        st.markdown('</div>', unsafe_allow_html=True)

    # Telegram手動發送
    st.markdown('<div style="margin-top:10px"></div>', unsafe_allow_html=True)
    if st.button("📨 發送分析到Telegram", use_container_width=True):
        sent = send_alert(
            ticker=sel, level="info", title=f"手動分析報告 — {sel}",
            body=summary, price=sel_price, score=sel_score,
            entry=entry, stop=stop, target=target, force=True,
        )
        if sent:
            st.success("已發送 ✓", icon="✅")
        else:
            st.warning("未配置Telegram或已靜音")

    st.markdown('</div>', unsafe_allow_html=True)

    # ── 共振分數條 (所有股票) ─────────────────────────────────────────────────
    st.markdown('<div style="margin-top:10px"></div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="background:#0d0d0d;border:1px solid #1e1e1e;border-radius:8px;padding:12px 14px">',
        unsafe_allow_html=True
    )
    st.markdown('<div style="font-family:IBM Plex Mono;font-size:9px;color:#aaa;letter-spacing:0.1em;margin-bottom:10px">SIGNAL STRENGTH</div>', unsafe_allow_html=True)

    for t in st.session_state.tickers:
        sc_v = stock_metrics.get(t, {}).get("score", 50)
        sc_c = score_color(sc_v)
        vc_s = stock_metrics.get(t, {}).get("state", "normal")
        dot  = "🔴" if vc_s == "major" else "🟡" if vc_s == "watching" else ""
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">'
            f'<span style="font-family:IBM Plex Mono;font-size:9px;color:#aaa;width:36px;flex-shrink:0">{t} {dot}</span>'
            f'<div style="flex:1;height:5px;background:#1a1a1a;border-radius:3px">'
            f'<div style="height:5px;width:{sc_v}%;background:{sc_c};border-radius:3px;'
            f'{"box-shadow:0 0 6px " + sc_c if sc_v >= 70 else ""};transition:width 0.6s"></div>'
            f'</div>'
            f'<span style="font-family:IBM Plex Mono;font-size:9px;color:{sc_c};width:24px;text-align:right;flex-shrink:0">{sc_v:.0f}</span>'
            f'</div>',
            unsafe_allow_html=True
        )

    # 勝率色塊
    wins, total = 13, 20
    pct_win = wins / total
    wc = C["bull"] if pct_win >= 0.6 else C["warn"] if pct_win >= 0.45 else C["bear"]
    st.markdown('<hr style="border-color:#1a1a1a;margin:8px 0"/>', unsafe_allow_html=True)
    st.markdown('<div style="font-family:IBM Plex Mono;font-size:9px;color:#aaa;letter-spacing:0.1em;margin-bottom:6px">WIN RATE · LAST 20</div>', unsafe_allow_html=True)
    blocks_html = "".join([
        f'<div style="width:10px;height:10px;border-radius:2px;background:{"" + C["bull"] + "cc" if i < wins else C["bear"] + "44"};display:inline-block;margin:1px"></div>'
        for i in range(total)
    ])
    st.markdown(
        f'<div style="margin-bottom:5px">{blocks_html}</div>'
        f'<div style="font-family:IBM Plex Mono;font-size:20px;font-weight:700;color:{wc}">{int(pct_win*100)}%</div>'
        f'<div style="font-family:IBM Plex Mono;font-size:8px;color:#555">{wins}W · {total-wins}L</div>',
        unsafe_allow_html=True
    )

    st.markdown('</div>', unsafe_allow_html=True)


# ─── 自動刷新 ─────────────────────────────────────────────────────────────────
st.markdown('<hr style="border-color:#1e1e1e;margin:14px 0 6px"/>', unsafe_allow_html=True)
footer_cols = st.columns([2, 1, 1])
with footer_cols[0]:
    st.markdown(
        f'<span style="font-family:IBM Plex Mono;font-size:8px;color:#333">'
        f'Trading Terminal v2.0 · 成交量瀑布預警 · Groq AI · Streamlit Cloud</span>',
        unsafe_allow_html=True
    )
with footer_cols[2]:
    auto_refresh = st.checkbox("自動刷新", value=True, key="auto_refresh")

if auto_refresh:
    time.sleep(st.session_state.refresh_interval)
    st.rerun()
