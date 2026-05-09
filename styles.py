"""
styles.py
全局CSS — 深色終端風格
IBM Plex Mono數字 + 視覺先於文字設計語言
"""

TERMINAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;700&display=swap');

/* ── Global ── */
html, body, [class*="css"] {
    background-color: #080808 !important;
    color: #e8e4dc !important;
}
.stApp { background: #080808; }
.block-container { padding: 1rem 1.5rem 2rem !important; max-width: 100% !important; }

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.stDeployButton { display: none; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 3px; height: 3px; }
::-webkit-scrollbar-track { background: #0d0d0d; }
::-webkit-scrollbar-thumb { background: #2a2a2a; border-radius: 2px; }

/* ── Mono numbers everywhere ── */
.mono { font-family: 'IBM Plex Mono', monospace !important; }
[data-testid="stMetricValue"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 1.3rem !important;
}

/* ── Metric cards ── */
[data-testid="stMetric"] {
    background: #0d0d0d !important;
    border: 1px solid #1e1e1e !important;
    border-radius: 8px !important;
    padding: 12px 14px !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0a0a0a !important;
    border-right: 1px solid #1a1a1a !important;
}
[data-testid="stSidebar"] label { color: #aaa !important; font-size: 0.75rem !important; }

/* ── Inputs ── */
.stTextInput input, .stNumberInput input, .stSelectbox select {
    background: #0d0d0d !important;
    border: 1px solid #2a2a2a !important;
    color: #e8e4dc !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
}
.stTextInput input:focus, .stSelectbox select:focus {
    border-color: #6fcf97 !important;
    box-shadow: 0 0 0 1px #6fcf9733 !important;
}

/* ── Buttons ── */
.stButton button {
    background: #0d0d0d !important;
    border: 1px solid #2a2a2a !important;
    color: #e8e4dc !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 0.75rem !important;
    transition: border-color 0.2s, background 0.2s !important;
}
.stButton button:hover {
    border-color: #6fcf97 !important;
    background: #141414 !important;
}

/* ── Toggle/Checkbox ── */
.stCheckbox label { color: #aaa !important; font-size: 0.75rem !important; }

/* ── Divider ── */
hr { border-color: #1e1e1e !important; }

/* ── Plotly chart background ── */
.js-plotly-plot .plotly, .js-plotly-plot .plotly bg {
    background: transparent !important;
}

/* ── Alert boxes (custom HTML) ── */
.vc-warn {
    background: #f2c94c10;
    border: 1px solid #f2c94c44;
    border-left: 3px solid #f2c94c;
    border-radius: 6px;
    padding: 10px 14px;
    margin: 4px 0;
    font-family: 'IBM Plex Mono', monospace;
}
.vc-danger {
    background: #eb575720;
    border: 1px solid #eb575760;
    border-left: 3px solid #eb5757;
    border-radius: 6px;
    padding: 10px 14px;
    margin: 4px 0;
    font-family: 'IBM Plex Mono', monospace;
    animation: pulse-border 1s ease-in-out 3;
}
.vc-normal {
    background: #0d0d0d;
    border: 1px solid #1e1e1e;
    border-left: 3px solid #444;
    border-radius: 6px;
    padding: 10px 14px;
    margin: 4px 0;
    font-family: 'IBM Plex Mono', monospace;
}

/* ── Volume ratio bar ── */
.vol-bar-container {
    background: #1a1a1a;
    border-radius: 3px;
    height: 5px;
    width: 100%;
    margin: 4px 0;
}
.vol-bar-fill {
    height: 5px;
    border-radius: 3px;
    transition: width 0.5s ease;
}

/* ── Signal ring (resonance) ── */
@keyframes pulse-border {
    0%,100% { box-shadow: 0 0 0 0 rgba(235,87,87,0); }
    50%      { box-shadow: 0 0 0 4px rgba(235,87,87,0.3); }
}
@keyframes breathe {
    0%,100% { opacity: 1; }
    50%      { opacity: 0.4; }
}
.live-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #6fcf97;
    animation: breathe 1.4s ease-in-out infinite;
    margin-right: 6px;
    vertical-align: middle;
}
.warn-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #f2c94c;
    animation: breathe 0.8s ease-in-out infinite;
    margin-right: 6px;
    vertical-align: middle;
}
.danger-dot {
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    background: #eb5757;
    animation: breathe 0.5s ease-in-out infinite;
    margin-right: 6px;
    vertical-align: middle;
}
</style>
"""

def inject_css():
    """每次rerun注入CSS，不cache"""
    import streamlit as st
    st.markdown(TERMINAL_CSS, unsafe_allow_html=True)
