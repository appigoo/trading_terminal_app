"""
data_engine.py
多層數據獲取引擎 — 應對Streamlit Cloud IP限制
Layer 1: yfinance + curl_cffi
Layer 2: yfinance 標準
Layer 3: 磁碟快取
Layer 4: 返回錯誤dict
"""
import pandas as pd
import numpy as np
import streamlit as st
import time
import hashlib
import os
import pickle
from datetime import datetime, timedelta

CACHE_DIR = "/tmp/trading_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_path(ticker: str, interval: str) -> str:
    key = hashlib.md5(f"{ticker}_{interval}".encode()).hexdigest()[:8]
    return os.path.join(CACHE_DIR, f"{key}.pkl")


def _load_cache(ticker: str, interval: str, max_age_min: int = 5):
    path = _cache_path(ticker, interval)
    if not os.path.exists(path):
        return None
    age = (time.time() - os.path.getmtime(path)) / 60
    if age > max_age_min:
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _save_cache(ticker: str, interval: str, df: pd.DataFrame):
    try:
        with open(_cache_path(ticker, interval), "wb") as f:
            pickle.dump(df, f)
    except Exception:
        pass


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """攤平yfinance MultiIndex欄位"""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


@st.cache_data(ttl=60, show_spinner=False)
def fetch_ohlcv(ticker: str, interval: str = "5m", period: str = "1d") -> pd.DataFrame:
    """
    獲取OHLCV數據，四層fallback
    interval: "5m" | "15m" | "1d"
    """
    cached = _load_cache(ticker, interval)
    if cached is not None:
        return cached

    # Layer 1: yfinance + curl_cffi
    try:
        import yfinance as yf
        try:
            from curl_cffi import requests as curl_requests
            session = curl_requests.Session(impersonate="chrome110")
            t = yf.Ticker(ticker, session=session)
        except Exception:
            t = yf.Ticker(ticker)

        df = t.history(period=period, interval=interval, auto_adjust=True)
        df = _flatten(df)
        if not df.empty:
            _save_cache(ticker, interval, df)
            return df
    except Exception:
        pass

    # Layer 2: yfinance 標準
    try:
        import yfinance as yf
        df = yf.download(ticker, period=period, interval=interval,
                         auto_adjust=True, progress=False)
        df = _flatten(df)
        if not df.empty:
            _save_cache(ticker, interval, df)
            return df
    except Exception:
        pass

    # Layer 3: 舊快取（不管過期）
    path = _cache_path(ticker, interval)
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                return pickle.load(f)
        except Exception:
            pass

    # Layer 4: 空DataFrame
    return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_vix() -> float:
    """獲取VIX指數"""
    try:
        df = fetch_ohlcv("^VIX", interval="1d", period="5d")
        if not df.empty:
            return float(df["Close"].iloc[-1])
    except Exception:
        pass
    return 18.5


@st.cache_data(ttl=60, show_spinner=False)
def fetch_quote(ticker: str) -> dict:
    """獲取最新報價快照"""
    try:
        import yfinance as yf
        try:
            from curl_cffi import requests as curl_requests
            session = curl_requests.Session(impersonate="chrome110")
            t = yf.Ticker(ticker, session=session)
        except Exception:
            t = yf.Ticker(ticker)

        info = t.fast_info
        return {
            "price":    float(info.last_price or 0),
            "prev":     float(info.previous_close or 0),
            "change1d": float(((info.last_price or 0) / (info.previous_close or 1) - 1) * 100),
            "volume":   int(info.three_month_average_volume or 0),
            "mktcap":   float(info.market_cap or 0),
        }
    except Exception:
        # Fallback from daily OHLCV
        df = fetch_ohlcv(ticker, interval="1d", period="5d")
        if not df.empty:
            price = float(df["Close"].iloc[-1])
            prev  = float(df["Close"].iloc[-2]) if len(df) > 1 else price
            return {
                "price": price, "prev": prev,
                "change1d": (price / prev - 1) * 100 if prev else 0,
                "volume": int(df["Volume"].iloc[-1]),
                "mktcap": 0,
            }
        return {"price": 0, "prev": 0, "change1d": 0, "volume": 0, "mktcap": 0}
