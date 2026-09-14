"""
Instant Trending & High Volume Flow Tracker
رصد فوري وسريع لأكثر العملات تفاعلاً وحجم تداول في السوق
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

# ============ الإعدادات المباشرة الفورية ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط مرنة جداً لضمان امتلاء الداشبورد بالنتائج فوراً
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 1000))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 500))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 8))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = 30

app = FastAPI(title="Instant Trending Flow Tracker")

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
        }, timeout=6)
    except Exception:
        pass


def get_instant_trending_pairs():
    """جلب أزواج العملات الأكثر تفاعلاً ورواجاً في السوق لحظياً"""
    pairs_list = []
    
    # نقطة النهاية الرسمية للعملات الأكثر رواجاً ونشاطاً
    url = "https://api.dexscreener.com/latest/dex/search?q=trending"
    try:
        r = requests.get(url, timeout=6)
        if r.status_code == 200:
            data = r.json()
            items = data.get("pairs", [])
            if isinstance(items, list):
                pairs_list.extend(items)
    except Exception:
        pass

    # إذا كانت النتائج قليلة، نجلب أحدث الـ Boosts المتاحة كدعم إضافي
    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=6)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addresses = [b.get("tokenAddress") for b in boosts[:15] if b.get("tokenAddress")]
                if addresses:
                    r3 = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses)}", timeout=6)
                    if r3.status_code == 200:
                        p_data = r3.json().get("pairs", [])
                        if isinstance(p_data, list):
                            pairs_list.extend(p_data)
    except Exception:
        pass

    # إزالة التكرار بناءً على عنوان العقد
    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_and_push_instant(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown")
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
    if h1_vol < MIN_VOLUME_USD:
        return

    txns = pair.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair.get("baseToken", {}).get("symbol", "?")
    name = pair.get("baseToken", {}).get("name", "Token")
    price = pair.get("priceUsd", "?")
    mcap = pair.get("fdv", pair.get("marketCap", "?"))
    pair_url = pair.get("url", "")

    status_text = f"🔥 نشط [شراء: {h1_buys} | بيع: {h1_sells}]"

    entry = {
        "type": "instant_trending",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id.upper(),
        "symbol": symbol,
        "name": name,
        "token_address": token_address,
        "price": price,
        "mcap": mcap,
        "liquidity": liq_usd,
        "volume": h1_vol,
        "buys": h1_buys,
        "sells": h1_sells,
        "url": pair_url,
        "safety": status_text,
        "strength": float(h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"⚡ *رصد سيولة نشطة* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحركة: {status_text}\n"
        f"الحجم (1h): ${h1_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_instant_trending_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_and_push_instant, p)
                stats["scanned_tokens"] += 1
            
        stats["last_scan"] = datetime.now(timezone.utc).isoformat()
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


app.mount("/static", StaticFiles(directory="static"), name="static")
