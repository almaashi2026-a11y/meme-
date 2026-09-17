"""
Smart Money & Pump Radar (Omni-Chain Instant Fire Edition)
الرادار الفوري الشامل لجميع السلاسل - إظهار النتائج بلا توقف
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

# ============ إعدادات الظهور الفوري (بدون فلاتر معقدة تحجب النتائج) ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط مرنة جداً لضمان ظهور النتائج فوراً على الداشبورد
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 50))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 10))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 1.0))
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 60  # تقليل وقت التبرع لتظهر العملات بسرعة

app = FastAPI(title="Smart Money & Pump Radar")

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
        }, timeout=2)
    except Exception:
        pass


def fetch_all_active_pairs():
    """جلب أضخم قائمة ممكنة من العملات وأحدثها على الإطلاق لضمان ظهور النتائج"""
    pairs_list = []
    
    # 1. أحدث الـ Token Profiles
    try:
        r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=2)
        if r.status_code == 200:
            profiles = r.json()
            if isinstance(profiles, list):
                addrs = [p.get("tokenAddress") for p in profiles[:100] if p.get("tokenAddress")]
                if addrs:
                    for i in range(0, len(addrs), 30):
                        chunk = addrs[i:i+30]
                        rt = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(chunk)}", timeout=2)
                        if rt.status_code == 200:
                            items = rt.json().get("pairs", [])
                            if isinstance(items, list):
                                pairs_list.extend(items)
    except Exception:
        pass

    # 2. أحدث الـ Token Boosts
    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=2)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addrs_b = [b.get("tokenAddress") for b in boosts[:60] if b.get("tokenAddress")]
                if addrs_b:
                    rb = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addrs_b[:30])}", timeout=2)
                    if rb.status_code == 200:
                        p_data = rb.json().get("pairs", [])
                        if isinstance(p_data, list):
                            pairs_list.extend(p_data)
    except Exception:
        pass

    # 3. بحث شامل ومتنوع لجميع الشبكات والكلمات الساخنة
    queries = ["sol", "base", "eth", "bsc", "pump", "ai", "meme", "pepe", "doge", "cat", "sui", "arb"]
    for q in queries:
        try:
            rq = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={q}", timeout=1.5)
            if rq.status_code == 200:
                items = rq.json().get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items[:25])
        except Exception:
            pass

    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_and_push(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown").upper()
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
    if h1_vol < MIN_VOLUME_USD:
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
    
    price_change = pair.get("priceChange", {})
    h1_change = float(price_change.get("h1", 0) or 0)

    status_text = f"🚀 رصد نشاط لحظي [1h: {h1_change:+.1f}%] [سيولة: ${liq_usd:,.0f}]"

    entry = {
        "type": "instant_radar",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "name": name,
        "token_address": token_address,
        "price": price,
        "mcap": mcap,
        "liquidity": liq_usd,
        "volume": h1_vol,
        "url": pair_url,
        "safety": status_text,
        "strength": float(liq_usd + h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🎯 *رصد عملة جديدة* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(fetch_all_active_pairs)
        if pairs:
            for p in pairs:
                stats["scanned_tokens"] += 1
                await asyncio.to_thread(analyze_and_push, p)
            
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
