"""
volume_cascade.py
成交量瀑布預警狀態機
5min K線量能 ≥ 前5根均量 → 第一警號 → 立即監視15min
15min K線量能 ≥ 前5根均量 → 大事預警
"""
import streamlit as st
import pandas as pd
import time
from datetime import datetime


# ─── 狀態機 (存於session_state) ──────────────────────────────────────────────
def _state_key(ticker: str) -> str:
    return f"vc_state_{ticker}"

def _log_key(ticker: str) -> str:
    return f"vc_log_{ticker}"


def get_cascade_state(ticker: str) -> str:
    return st.session_state.get(_state_key(ticker), "normal")


def set_cascade_state(ticker: str, state: str):
    st.session_state[_state_key(ticker)] = state


def get_cascade_log(ticker: str) -> list:
    return st.session_state.get(_log_key(ticker), [])


def add_cascade_log(ticker: str, entry: dict):
    key = _log_key(ticker)
    log = st.session_state.get(key, [])
    log.insert(0, entry)
    st.session_state[key] = log[:50]  # 保留最近50條


# ─── 核心計算 ─────────────────────────────────────────────────────────────────
def _vol_ratio(df: pd.DataFrame) -> float:
    """當前K線量 / 前5根均量"""
    if df is None or len(df) < 6:
        return 0.0
    cur = df["Volume"].iloc[-1]
    avg = df["Volume"].iloc[-6:-1].mean()
    return float(cur / avg) if avg > 0 else 0.0


def run_cascade(ticker: str, df_5m: pd.DataFrame, df_15m: pd.DataFrame,
                threshold: float = 1.0) -> dict:
    """
    執行一次成交量瀑布檢查
    返回:
      state       : "normal" | "watching" | "major"
      alert_level : "none" | "warn" | "danger"
      ratio_5m    : float
      ratio_15m   : float
      message     : str
      new_event   : bool  — 是否剛剛觸發新事件
    """
    ratio_5m  = _vol_ratio(df_5m)
    ratio_15m = _vol_ratio(df_15m)
    state     = get_cascade_state(ticker)
    now_str   = datetime.now().strftime("%H:%M:%S")
    new_event = False

    if state == "normal":
        if ratio_5m >= threshold:
            set_cascade_state(ticker, "watching")
            new_event = True
            entry = {
                "time": now_str, "ticker": ticker,
                "level": "warn",
                "msg": f"🔔 5min量能 {ratio_5m:.2f}× — 升級監視15min",
                "ratio": ratio_5m,
            }
            add_cascade_log(ticker, entry)
            return {
                "state": "watching", "alert_level": "warn",
                "ratio_5m": ratio_5m, "ratio_15m": ratio_15m,
                "message": entry["msg"], "new_event": True,
            }
        return {
            "state": "normal", "alert_level": "none",
            "ratio_5m": ratio_5m, "ratio_15m": ratio_15m,
            "message": "", "new_event": False,
        }

    elif state == "watching":
        if ratio_15m >= threshold:
            set_cascade_state(ticker, "major")
            new_event = True
            entry = {
                "time": now_str, "ticker": ticker,
                "level": "danger",
                "msg": f"🚨 大事預警！15min量能 {ratio_15m:.2f}× 確認",
                "ratio": ratio_15m,
            }
            add_cascade_log(ticker, entry)
            return {
                "state": "major", "alert_level": "danger",
                "ratio_5m": ratio_5m, "ratio_15m": ratio_15m,
                "message": entry["msg"], "new_event": True,
            }
        # 仍在監視中
        return {
            "state": "watching", "alert_level": "warn",
            "ratio_5m": ratio_5m, "ratio_15m": ratio_15m,
            "message": f"⏳ 監視15min中… 當前 {ratio_15m:.2f}×",
            "new_event": False,
        }

    elif state == "major":
        # 重置條件：量能回落正常
        if ratio_5m < threshold * 0.7 and ratio_15m < threshold * 0.7:
            set_cascade_state(ticker, "normal")
        return {
            "state": "major", "alert_level": "danger",
            "ratio_5m": ratio_5m, "ratio_15m": ratio_15m,
            "message": "🚨 大事預警持續中",
            "new_event": False,
        }

    return {"state": state, "alert_level": "none",
            "ratio_5m": ratio_5m, "ratio_15m": ratio_15m,
            "message": "", "new_event": False}
