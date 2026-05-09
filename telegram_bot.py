"""
telegram_bot.py
Telegram分級通知系統

觸發條件：
  🔴 DANGER — 成交量雙層確認 / VIX急升 / 多指標共振
  🟡 WARN   — 5min量能異動 / MACD死叉 / EMA空頭 / 共振跌破50
  🟢 INFO   — 共振≥70 / MACD金叉 / EMA多頭 / RSI極值

頻率控制：每個ticker每個訊號類型，N分鐘內最多發1次
去重機制：狀態機，只在「邊界跨越」時發送
"""
import streamlit as st
import requests
import hashlib
import time


# ─── 配置 ─────────────────────────────────────────────────────────────────────
def _get_config():
    token   = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
    return token, chat_id

def _global_muted() -> bool:
    return st.session_state.get("tg_global_mute", False)

def _cooldown_minutes() -> int:
    return st.session_state.get("tg_cooldown_min", 30)


# ─── 頻率控制 ─────────────────────────────────────────────────────────────────
def _rate_key(ticker: str, signal_type: str) -> str:
    """每個ticker+訊號類型獨立計時"""
    return f"tg_rate_{ticker}_{signal_type}"

def _can_send(ticker: str, signal_type: str, force: bool = False) -> bool:
    if force:
        return True
    if _global_muted():
        return False
    key = _rate_key(ticker, signal_type)
    last_sent = st.session_state.get(key, 0)
    elapsed_min = (time.time() - last_sent) / 60
    return elapsed_min >= _cooldown_minutes()

def _mark_rate(ticker: str, signal_type: str):
    st.session_state[_rate_key(ticker, signal_type)] = time.time()

def seconds_until_next(ticker: str, signal_type: str) -> int:
    """剩餘冷卻時間（秒），用於UI顯示"""
    key = _rate_key(ticker, signal_type)
    last = st.session_state.get(key, 0)
    cooldown_sec = _cooldown_minutes() * 60
    remaining = cooldown_sec - (time.time() - last)
    return max(0, int(remaining))


# ─── 核心發送 ─────────────────────────────────────────────────────────────────
def _send_raw(token: str, chat_id: str, text: str) -> bool:
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
        return resp.status_code == 200
    except Exception:
        return False

def send_alert(ticker: str, level: str, signal_type: str,
               title: str, body: str,
               price: float = 0, score: int = 0,
               entry: float = 0, stop: float = 0, target: float = 0,
               force: bool = False) -> bool:
    """
    發送Telegram通知（含頻率控制）

    ticker      : 股票代碼
    level       : "danger" | "warn" | "info"
    signal_type : 訊號類型字串，用於獨立計時（如 "resonance_high", "macd_cross"）
    force       : 忽略冷卻時間（手動發送用）
    """
    if not _can_send(ticker, signal_type, force):
        return False

    token, chat_id = _get_config()
    if not token or not chat_id:
        return False

    emoji     = {"danger": "🚨", "warn": "🔔", "info": "📗"}.get(level, "📊")
    level_tag = {"danger": "大事預警", "warn": "警號",    "info": "訊號" }.get(level, "通知")

    lines = [
        f"{emoji} *{level_tag} — {ticker}*",
        "━━━━━━━━━━━━━━━━━",
        f"📌 {title}",
        "",
        body,
    ]
    if price > 0:
        lines += ["", f"💰 價格：`${price:.2f}`"]
    if score > 0:
        lines += [f"📊 共振：`{score}/100`"]
    if entry > 0:
        lines += [
            "",
            f"🟡 Entry： `${entry:.2f}`",
            f"🔴 Stop：  `${stop:.2f}`",
            f"🟢 Target：`${target:.2f}`",
        ]

    ok = _send_raw(token, chat_id, "\n".join(lines))
    if ok:
        _mark_rate(ticker, signal_type)
    return ok


# ─── 各類型觸發函數 ───────────────────────────────────────────────────────────

def send_resonance_high(ticker: str, score: int, price: float,
                        entry: float, stop: float, target: float) -> bool:
    """共振分數 ≥ 70 — 入場訊號"""
    return send_alert(
        ticker=ticker, level="info", signal_type="resonance_high",
        title="共振評分突破70 — 入場訊號",
        body=(
            f"多指標共振確認，結構完整。\n"
            f"建議分批進場，嚴守止損。"
        ),
        price=price, score=score,
        entry=entry, stop=stop, target=target,
    )

def send_resonance_drop(ticker: str, score: int, price: float) -> bool:
    """共振分數跌破50 — 警示"""
    return send_alert(
        ticker=ticker, level="warn", signal_type="resonance_drop",
        title="共振評分跌破50 — 結構轉弱",
        body=f"訊號共振不足，建議觀望或減倉。",
        price=price, score=score,
    )

def send_macd_cross(ticker: str, is_golden: bool, price: float,
                    macd_val: float) -> bool:
    """MACD金叉 / 死叉"""
    label = "金叉" if is_golden else "死叉"
    level = "info" if is_golden else "warn"
    return send_alert(
        ticker=ticker, level=level, signal_type="macd_cross",
        title=f"MACD {label}",
        body=(
            f"MACD線穿越信號線{'向上' if is_golden else '向下'}。\n"
            f"MACD值：`{macd_val:+.3f}`"
        ),
        price=price,
    )

def send_ema_alignment(ticker: str, is_bull: bool, price: float) -> bool:
    """EMA多頭 / 空頭排列形成"""
    label = "多頭排列" if is_bull else "空頭排列"
    level = "info" if is_bull else "warn"
    return send_alert(
        ticker=ticker, level=level, signal_type="ema_align",
        title=f"EMA {label}形成",
        body=(
            f"EMA 8 {'>' if is_bull else '<'} EMA 21 {'>' if is_bull else '<'} EMA 55\n"
            f"{'趨勢確認，動能向上。' if is_bull else '趨勢轉弱，注意風險。'}"
        ),
        price=price,
    )

def send_vix_spike(vix_now: float, vix_prev: float, pct_change: float) -> bool:
    """VIX單日急升 > 15%"""
    return send_alert(
        ticker="VIX", level="danger", signal_type="vix_spike",
        title=f"VIX急升 {pct_change:.1f}% — 市場恐慌",
        body=(
            f"VIX：`{vix_prev:.1f}` → `{vix_now:.1f}`\n\n"
            f"市場恐慌急升，建議：\n"
            f"⏸ 暫停新倉\n"
            f"🔒 收緊止損\n"
            f"📉 降低槓桿"
        ),
    )

def send_multi_resonance(tickers_triggered: list, price_map: dict) -> bool:
    """3+股票同時觸發共振 — 升級DANGER"""
    ticker_lines = "\n".join(
        [f"  • {t}：`${price_map.get(t, 0):.2f}`" for t in tickers_triggered]
    )
    return send_alert(
        ticker="MARKET", level="danger", signal_type="multi_resonance",
        title=f"市場多股共振 — {len(tickers_triggered)}隻同時觸發",
        body=(
            f"以下股票同時達到共振條件：\n{ticker_lines}\n\n"
            f"多股同向，市場動能強烈。"
        ),
    )

def send_volume_cascade(ticker: str, ratio_5m: float, ratio_15m: float,
                        price: float, is_major: bool) -> bool:
    """成交量瀑布預警"""
    if is_major:
        return send_alert(
            ticker=ticker, level="danger", signal_type="vol_cascade_major",
            title="成交量瀑布 — 雙層確認",
            body=(
                f"5min量能：`{ratio_5m:.2f}×` 均量\n"
                f"15min量能：`{ratio_15m:.2f}×` 均量\n\n"
                "雙層確認，必定有重大異動。\n"
                "⏸ 暫停新倉，等待方向確認。"
            ),
            price=price,
        )
    else:
        return send_alert(
            ticker=ticker, level="warn", signal_type="vol_cascade_warn",
            title="5min量能異動 — 監視升級",
            body=(
                f"5min量能：`{ratio_5m:.2f}×` 均量\n"
                "已升級監視15min K線。\n"
                "⚠️ 保持警惕，勿追入。"
            ),
            price=price,
        )
