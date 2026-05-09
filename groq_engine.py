"""
groq_engine.py
Groq AI分析報告生成
雙層架構：規則系統先出結果，Groq驗證+擴展
"""
import streamlit as st
import json
import hashlib
import time


def _get_client():
    try:
        from groq import Groq
        api_key = st.secrets.get("GROQ_API_KEY", "")
        if not api_key:
            return None
        return Groq(api_key=api_key)
    except Exception:
        return None


def _dedup_key(ticker: str, score: int) -> str:
    bucket = score // 10  # 每10分一個bucket，避免重複
    hour = int(time.time() // 3600)
    return hashlib.md5(f"{ticker}_{bucket}_{hour}".encode()).hexdigest()[:8]


@st.cache_data(ttl=1800, show_spinner=False)
def groq_analysis(ticker: str, score: int, reasons: list,
                  price: float, rsi: float, macd: float,
                  ratio_5m: float, ratio_15m: float,
                  vix: float) -> dict:
    """
    生成AI分析報告
    返回 dict with keys: trend, entry, stop, target, kelly, summary, risks
    """
    client = _get_client()

    # 規則層：基礎計算（無論Groq是否可用）
    atr_est = price * 0.018
    up = score >= 65
    neutral = 45 <= score < 65

    rule_result = {
        "trend":   "多頭" if up else ("中性" if neutral else "空頭"),
        "entry":   round(price * 0.993, 2),
        "stop":    round(price * 0.975, 2),
        "target":  round(price * 1.035, 2),
        "kelly":   min(25, max(5, score // 5)),
        "rr":      round((price * 1.035 - price * 0.993) /
                         max(price * 0.993 - price * 0.975, 0.01), 1),
        "summary": _rule_summary(ticker, score, up, neutral, ratio_5m, ratio_15m),
        "risks":   _rule_risks(rsi, macd, score, vix, ratio_5m),
        "source":  "規則引擎",
    }

    if client is None:
        return rule_result

    # Groq驗證層
    try:
        vol_context = ""
        if ratio_5m >= 1.0:
            vol_context = f"⚠️ 5min量能異動 {ratio_5m:.2f}× 均量"
        if ratio_15m >= 1.0:
            vol_context = f"🚨 雙層量能確認 5m:{ratio_5m:.2f}× 15m:{ratio_15m:.2f}×"

        prompt = f"""你是專業量化交易分析師。以下是{ticker}的即時數據，請給出交易建議。

數據：
- 當前價格：${price:.2f}
- 共振分數：{score}/100
- RSI：{rsi:.1f}
- MACD：{macd:.3f}
- VIX：{vix:.1f}
- 成交量狀態：{vol_context if vol_context else "正常"}
- 觸發條件：{", ".join(reasons[:4])}

請嚴格按以下JSON格式輸出，不要有任何額外文字：
{{
  "trend": "多頭/空頭/中性",
  "entry": 數字,
  "stop": 數字,
  "target": 數字,
  "kelly": 整數,
  "summary": "120字內的分析摘要（繁體中文）",
  "risks": ["風險1", "風險2", "風險3"]
}}

規則：entry/stop/target基於ATR(≈{atr_est:.2f})計算，kelly介於5-25之間。"""

        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.3,
        )
        text = resp.choices[0].message.content.strip()
        # 清理markdown代碼塊
        text = text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)

        return {
            "trend":   data.get("trend", rule_result["trend"]),
            "entry":   float(data.get("entry", rule_result["entry"])),
            "stop":    float(data.get("stop", rule_result["stop"])),
            "target":  float(data.get("target", rule_result["target"])),
            "kelly":   int(data.get("kelly", rule_result["kelly"])),
            "rr":      round((float(data.get("target", rule_result["target"])) - float(data.get("entry", rule_result["entry"]))) /
                             max(float(data.get("entry", rule_result["entry"])) - float(data.get("stop", rule_result["stop"])), 0.01), 1),
            "summary": data.get("summary", rule_result["summary"]),
            "risks":   data.get("risks", rule_result["risks"]),
            "source":  "Groq AI",
        }
    except Exception:
        return rule_result


def _rule_summary(ticker, score, up, neutral, ratio_5m, ratio_15m):
    vol_note = ""
    if ratio_15m >= 1.0:
        vol_note = f"雙層量能確認({ratio_5m:.1f}×/{ ratio_15m:.1f}×)，大事預警。"
    elif ratio_5m >= 1.0:
        vol_note = f"5min量能異動({ratio_5m:.1f}×)，監視15min中。"

    if up:
        return f"{ticker} 共振分數{score}/100，多頭結構完整，EMA排列配合MACD確認動能。{vol_note}建議分批進場，嚴守止損。"
    elif neutral:
        return f"{ticker} 共振分數{score}/100，技術面尚未明確共振。{vol_note}等待突破確認再行動，控制倉位。"
    else:
        return f"{ticker} 共振分數{score}/100，空頭壓力明顯。{vol_note}不建議做多，若持倉應評估減倉。"


def _rule_risks(rsi, macd, score, vix, ratio_5m):
    risks = []
    risks.append("RSI超買，短線回調風險" if rsi > 70 else
                 "RSI超賣，注意反彈" if rsi < 30 else "RSI健康區間")
    risks.append("MACD負值，動能偏弱" if macd < 0 else "MACD正值，動能支持")
    risks.append("VIX偏高，市場恐慌" if vix > 25 else
                 "VIX中位，保持警惕" if vix > 18 else "VIX低位，環境有利")
    if ratio_5m >= 1.0:
        risks.append(f"量能異動{ratio_5m:.1f}×，注意方向確認")
    return risks[:3]
