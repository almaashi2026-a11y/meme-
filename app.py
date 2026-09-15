"""
First-Spark True Pre-Launch Radar (Zero-Delay Edition)
رصد حقيقي قبل الانفجار وفي اللحظة الأولى تماماً لتدفق السيولة على جميع السلاسل
"""

import asyncio
import time
import os
from collections import deque
from datetime import datetime, timezone

import requests
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ============ إعدادات رصد ما قبل الانفجار والشرارة الصافية ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 500))   # الحد الأدنى للسيولة في البداية
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 100))    # الحد الأدنى لتأكيد بداية ضخ الحجم

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 2.5))        # فحص أسرع لتجنب أي تأخير
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 120

app = FastAPI(title="True Pre-Launch Spark Radar")

alerts_feed = deque(maxlen=MAX_ALERTS_STORED)
stats = {"scanned_tokens": 0, "last_scan": None, "alerts_total": 0}
last_alert_time = {}


def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=5)
    except Exception:
        pass


def get_pre_launch_pairs():
    pairs_list = []
    # استعلامات شاملة لكل السلاسل لاصطياد أحدث العقود والسيولة الناشئة
    queries = ["pump", "sol", "base", "ai", "meme", "inu", "pepe", "cat", "doge", "eth", "bsc", "new"]
    for q in queries:
        url = f"https://api.dexscreener.com/latest/dex/search?q={q}"
        try:
            r = requests.get(url, timeout=3)
            if r.status_code == 200:
                data = r.json()
                items = data.get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items)
        except Exception:
            pass

    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=3)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addresses = [b.get("tokenAddress") for b in boosts[:40] if b.get("tokenAddress")]
                if addresses:
                    r3 = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses)}", timeout=3)
                    if r3.status_code == 200:
                        p_data = r3.json().get("pairs", [])
                        if isinstance(p_data, list):
                            pairs_list.extend(p_data)
    except Exception:
        pass

    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_pre_launch(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown").upper()
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    txns = pair.get("txns", {})
    m5 = txns.get("m5", {})
    m5_buys = m5.get("buys", 0) or 0
    m5_sells = m5.get("sells", 0) or 0
    
    m5_vol = float(pair.get("volume", {}).get("m5", 0) or 0)
    if m5_vol < MIN_VOLUME_USD:
        return

    price_change = pair.get("priceChange", {})
    m5_change = float(price_change.get("m5", 0) or 0)

    # =========================================================
    # استراتيجية "قبل الانفجار مباشرة" (True Pre-Launch / Zero Spark)
    # =========================================================
    # 1. منع رصد العملات المتأخرة: السعر لم يتحرك بعد بقوة (بين 0.2% و 12% فقط في أول 5 دقائق)
    if m5_change < 0.2 or m5_change > 12.0:
        return

    # 2. التأكد من أن صفقات الشراء بدأت تشتعل وتسيطر تماماً على الدقائق الأولى (بدون بيع يذكر)
    total_txns = m5_buys + m5_sells
    if total_txns < 3:
        return
    
    buy_ratio = m5_buys / total_txns
    if buy_ratio < 0.80:  # يجب أن يكون حجم صفقات الشراء 80% فأكثر (هجوم شرائي بحت في البداية)
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair.get("baseToken", {}).get("symbol", "?")
    name = pair.get("baseToken", {}).get("name", "Token")
    price = pair.get("priceUsd", "?")
    mcap = pair.get("fdv", pair.get("marketCap", "?"))
    pair_url = pair.get("url", "")

    status_text = f"🚀 [قنص قاع الشرارة] صعود مبكر: +{m5_change:.1f}% | شراء: {m5_buys} مقابل بيع: {m5_sells}"

    entry = {
        "type": "pre_launch_spark",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "name": name,
        "token_address": token_address,
        "price": price,
        "mcap": mcap,
        "liquidity": liq_usd,
        "volume": m5_vol,
        "buys": m5_buys,
        "sells": m5_sells,
        "url": pair_url,
        "safety": status_text,
        "strength": float(m5_vol * buy_ratio * (1 + m5_change))
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🎯 *رصد قبل الانفجار (الشرارة الأولى)* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"حجم 5د: ${m5_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        try:
            pairs = await asyncio.to_thread(get_pre_launch_pairs)
            if pairs:
                for p in pairs:
                    await asyncio.to_thread(analyze_pre_launch, p)
                    stats["scanned_tokens"] += 1
                
            stats["last_scan"] = datetime.now(timezone.utc).isoformat()
        except Exception:
            pass
        await asyncio.sleep(POLL_SECONDS)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scanner_loop())


@app.get("/api/alerts")
def api_alerts():
    sorted_alerts = sorted(list(alerts_feed), key=lambda x: x.get("strength", 0), reverse=True)
    return JSONResponse({"alerts": sorted_alerts, "stats": stats})


@app.get("/")
def dashboard():
    return FileResponse("static/index.html")


if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")
