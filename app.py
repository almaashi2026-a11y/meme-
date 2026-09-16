"""
Zero-Delay Raw Spark Radar (Direct Pool Monitoring)
رصد أحدث أزواج السيولة الخام لحظياً وبدون أي تأخير يذكر
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

# ============ إعدادات الرصد الصفرية بدون تأخير ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط أولية منخفضة جداً للقبض على العملة في ثوانيها الأولى
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 200))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 30))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 1.0))  # فحص سريع جداً كل ثانية
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 240

app = FastAPI(title="Zero-Delay Raw Spark Radar")

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
        }, timeout=3)
    except Exception:
        pass


def get_raw_latest_pools():
    """جلب أحدث أزواج السيولة الخام مباشرة عبر عدة قنوات بحثية متسارعة"""
    pairs_list = []
    
    # 1. البحث المباشر عن الكلمات والرموز الأكثر تداولا لحظياً لسرعة التحديث
    hot_terms = ["sol", "pump", "usdt", "eth", "base", "ai", "meme", "doge", "cat", "pepe", "bsc", "arb"]
    for term in hot_terms:
        try:
            r = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={term}", timeout=2.5)
            if r.status_code == 200:
                data = r.json()
                items = data.get("pairs", [])
                if isinstance(items, list):
                    # نأخذ أحدث النتائج الخام المعروضة
                    pairs_list.extend(items[:25])
        except Exception:
            pass

    # 2. دمج أحدث الـ Token Profiles كدعم إضافي
    try:
        r_prof = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=2.5)
        if r_prof.status_code == 200:
            profiles = r_prof.json()
            if isinstance(profiles, list):
                addrs = [p.get("tokenAddress") for p in profiles[:25] if p.get("tokenAddress")]
                if addrs:
                    r_t = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addrs)}", timeout=2.5)
                    if r_t.status_code == 200:
                        items = r_t.json().get("pairs", [])
                        if isinstance(items, list):
                            pairs_list.extend(items)
    except Exception:
        pass

    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_raw_pair(pair):
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

    price_change = pair.get("priceChange", {})
    h1_change = float(price_change.get("h1", 0) or 0)

    # فلتر الاحتراف للقبض على بداية الانفجار فقط وعدم التأخر في القمم العالية
    # نستهدف العملات التي في بداية صعودها (بين 0% إلى 80% كحد أقصى)
    if h1_change < -5.0 or h1_change > 80.0:
        return

    txns = pair.get("txns", {})
    m5 = txns.get("m5", {})
    m5_buys = m5.get("buys", 0) or 0
    m5_sells = m5.get("sells", 0) or 0

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair.get("baseToken", {}).get("symbol", "?")
    name = pair.get("baseToken", {}).get("name", "Token")
    price = pair.get("priceUsd", "?")
    mcap = pair.get("fdv", pair.get("marketCap", "?"))
    pair_url = pair.get("url", "")

    status_text = f"⚡ رصد الانطلاقة الأولى [1h: +{h1_change:.1f}%] (شراء 5m: {m5_buys})"

    entry = {
        "type": "raw_spark",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "name": name,
        "token_address": token_address,
        "price": price,
        "mcap": mcap,
        "liquidity": liq_usd,
        "volume": h1_vol,
        "buys": m5_buys,
        "sells": m5_sells,
        "url": pair_url,
        "safety": status_text,
        "strength": float(h1_vol * (1 + h1_change))
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🎯 *رصد الشرارة المبكرة* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"الحجم: ${h1_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_raw_latest_pools)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_raw_pair, p)
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
