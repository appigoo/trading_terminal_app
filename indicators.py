"""
indicators.py
純Python技術指標計算 — 不依賴TA-Lib，Streamlit Cloud相容
包含：EMA、RSI(Wilder)、MACD、ATR、成交量均值
"""
import pandas as pd
import numpy as np


# ─── EMA ─────────────────────────────────────────────────────────────────────
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


# ─── RSI (Wilder平滑) ─────────────────────────────────────────────────────────
def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


# ─── MACD ────────────────────────────────────────────────────────────────────
def macd(series: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ─── ATR (Wilder) ────────────────────────────────────────────────────────────
def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ─── 成交量均值 ───────────────────────────────────────────────────────────────
def volume_avg(volume: pd.Series, period: int = 5) -> pd.Series:
    return volume.rolling(period).mean()


# ─── 成交量瀑布預警 ──────────────────────────────────────────────────────────
def volume_cascade_check(df_5m: pd.DataFrame, df_15m: pd.DataFrame, threshold: float = 1.0):
    """
    返回 dict:
      alert_5m   : bool  — 5min K線量能觸發
      ratio_5m   : float — 當前量/前5根均量
      alert_15m  : bool  — 15min K線量能確認
      ratio_15m  : float
      major_event: bool  — 兩層均觸發
    """
    result = {
        "alert_5m": False, "ratio_5m": 0.0,
        "alert_15m": False, "ratio_15m": 0.0,
        "major_event": False,
    }

    if df_5m is not None and len(df_5m) >= 6:
        cur_5m = df_5m["Volume"].iloc[-1]
        avg_5m = df_5m["Volume"].iloc[-6:-1].mean()
        if avg_5m > 0:
            ratio = cur_5m / avg_5m
            result["ratio_5m"] = round(ratio, 2)
            result["alert_5m"] = ratio >= threshold

    if df_15m is not None and len(df_15m) >= 6:
        cur_15m = df_15m["Volume"].iloc[-1]
        avg_15m = df_15m["Volume"].iloc[-6:-1].mean()
        if avg_15m > 0:
            ratio = cur_15m / avg_15m
            result["ratio_15m"] = round(ratio, 2)
            result["alert_15m"] = ratio >= threshold

    result["major_event"] = result["alert_5m"] and result["alert_15m"]
    return result


# ─── 共振評分 (0-100) ─────────────────────────────────────────────────────────
def resonance_score(df: pd.DataFrame, vix_value: float = 18.0) -> dict:
    """
    多指標共振評分系統
    返回 score(0-100) 和 reasons list
    """
    if df is None or len(df) < 60:
        return {"score": 50, "reasons": ["數據不足"]}

    close = df["Close"]
    volume = df["Volume"]

    e8  = ema(close, 8).iloc[-1]
    e21 = ema(close, 21).iloc[-1]
    e55 = ema(close, 55).iloc[-1]
    rsi_val = rsi(close).iloc[-1]
    macd_l, macd_s, macd_h = macd(close)
    macd_val  = macd_l.iloc[-1]
    macd_sig  = macd_s.iloc[-1]
    macd_hist = macd_h.iloc[-1]
    vol_avg5 = volume_avg(volume, 5).iloc[-1]
    cur_vol  = volume.iloc[-1]
    price    = close.iloc[-1]

    score = 0
    reasons = []

    # EMA排列 25分
    if e8 > e21 > e55:
        score += 25
        reasons.append("EMA多頭排列 ✅")
    elif e8 < e21 < e55:
        score -= 10
        reasons.append("EMA空頭排列 ❌")
    else:
        reasons.append("EMA排列混亂 ⚠️")

    # RSI位置 20分
    if 50 < rsi_val < 70:
        score += 20
        reasons.append(f"RSI健康多頭區 ({rsi_val:.1f}) ✅")
    elif rsi_val >= 70:
        score += 5
        reasons.append(f"RSI超買 ({rsi_val:.1f}) ⚠️")
    elif 30 < rsi_val <= 50:
        score += 8
        reasons.append(f"RSI弱勢區 ({rsi_val:.1f}) ⚠️")
    else:
        score += 15  # 超賣反彈機會
        reasons.append(f"RSI超賣 ({rsi_val:.1f}) — 反彈機會")

    # MACD 20分
    if macd_val > macd_sig and macd_hist > 0:
        score += 20
        reasons.append("MACD金叉+正柱 ✅")
    elif macd_val > macd_sig:
        score += 10
        reasons.append("MACD金叉 ✅")
    elif macd_hist > 0:
        score += 8
        reasons.append("MACD正柱 ⚠️")
    else:
        reasons.append("MACD空頭 ❌")

    # 成交量 20分
    if vol_avg5 > 0:
        vol_ratio = cur_vol / vol_avg5
        if vol_ratio >= 1.5:
            score += 20
            reasons.append(f"量能爆發 {vol_ratio:.1f}× ✅")
        elif vol_ratio >= 1.0:
            score += 12
            reasons.append(f"量能正常 {vol_ratio:.1f}× ✅")
        else:
            score += 4
            reasons.append(f"量能萎縮 {vol_ratio:.1f}× ⚠️")

    # VIX濾網 15分
    if vix_value < 18 and vix_value > 0:
        score += 15
        reasons.append(f"VIX低位 ({vix_value:.1f}) ✅")
    elif vix_value < 25:
        score += 8
        reasons.append(f"VIX中位 ({vix_value:.1f}) ⚠️")
    else:
        score -= 15
        reasons.append(f"VIX偏高 ({vix_value:.1f}) ❌")

    score = max(0, min(100, score))
    return {"score": score, "reasons": reasons,
            "rsi": rsi_val, "macd": macd_val, "macd_hist": macd_hist,
            "ema8": e8, "ema21": e21, "ema55": e55}
