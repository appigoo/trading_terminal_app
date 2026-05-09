"""
telegram_bot.py
Telegram分級通知系統
🔴 DANGER — 立即發送（大事預警）
🟡 WARN   — 限流發送（第一警號）
🟢 INFO   — 每日彙整
"""
import streamlit as st
import requests
import hashlib
import time


def _get_config():
    token   = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def _dedup_key(ticker: str, level: str, msg_type: str) -> str:
    hour = int(time.time() // 3600)
    return hashlib.md5(f"{ticker}_{level}_{msg_type}_{hour}".encode()).hexdigest()[:8]


def _already_sent(key: str) -> bool:
    sent = st.session_state.get("tg_sent_keys", set())
    return key in sent


def _mark_sent(key: str):
    if "tg_sent_keys" not in st.session_state:
        st.session_state["tg_sent_keys"] = set()
    st.session_state["tg_sent_keys"].add(key)


def _global_muted() -> bool:
    return st.session_state.get("tg_global_mute", False)


def send_alert(ticker: str, level: str, title: str, body: str,
               price: float = 0, score: int = 0,
               entry: float = 0, stop: float = 0, target: float = 0,
               force: bool = False) -> bool:
    """
    發送Telegram通知
    level: "danger" | "warn" | "info"
    返回 True if sent
    """
    if _global_muted() and not force:
        return False

    token, chat_id = _get_config()
    if not token or not chat_id:
        return False

    dedup_key = _dedup_key(ticker, level, title)
    if _already_sent(dedup_key) and not force:
        return False

    emoji = {"danger": "🚨", "warn": "🔔", "info": "📊"}.get(level, "📊")
    level_tag = {"danger": "大事預警", "warn": "第一警號", "info": "資訊"}.get(level, "通知")

    lines = [
        f"{emoji} *{level_tag} — {ticker}*",
        f"━━━━━━━━━━━━━━━━━",
        f"📌 {title}",
        f"",
        body,
    ]

    if price > 0:
        lines += ["", f"💰 當前價格：`${price:.2f}`"]
    if score > 0:
        lines += [f"📊 共振分數：`{score}/100`"]
    if entry > 0:
        lines += [
            "",
            f"🟡 Entry：`${entry:.2f}`",
            f"🔴 Stop： `${stop:.2f}`",
            f"🟢 Target：`${target:.2f}`",
        ]

    text = "\n".join(lines)

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
        if resp.status_code == 200:
            _mark_sent(dedup_key)
            return True
    except Exception:
        pass
    return False


def send_volume_cascade(ticker: str, ratio_5m: float, ratio_15m: float,
                        price: float, is_major: bool) -> bool:
    if is_major:
        return send_alert(
            ticker=ticker, level="danger",
            title="成交量瀑布 — 雙層確認",
            body=(
                f"5min量能：`{ratio_5m:.2f}×` 均量\n"
                f"15min量能：`{ratio_15m:.2f}×` 均量\n\n"
                "雙層確認觸發，必定有重大異動。\n"
                "⏸ 暫停新倉，等待方向確認。"
            ),
            price=price,
        )
    else:
        return send_alert(
            ticker=ticker, level="warn",
            title="5min量能異動 — 監視升級",
            body=(
                f"5min量能：`{ratio_5m:.2f}×` 均量\n"
                "已升級監視15min K線。\n"
                "⚠️ 保持警惕，勿追入。"
            ),
            price=price,
        )
