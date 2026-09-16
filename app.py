"""
Instant Volume & Pump Surge Radar (Zero-Lag Edition)
رصد الانفجارات السعرية وحجم التداول اللحظي لجميع السلاسل قبل اختفاء الحركة
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

# ============ الإعدادات الاحترافية لترصد الانفجار اللحظي ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط تضمن أن العملة تشهد سيولة وحركة حقيقية وليست ميتة
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 500))
MIN_VOLUME_5M = float(os.environ.get("MIN_VOLUME_5M", 500))  # تركيز على حجم آخر 5 دقائق

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 1.0))
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 120

app = FastAPI(title="Instant Volume Surge Radar")

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


def get_instant_surge_pairs():
    """جلب الأزواج التي تشهد نشاطاً غير طبيعي في اللحظة الحالية عبر استعلامات شاملة"""
    pairs_list = []
    
    # شبكات وكلمات مفتاحية تغطي أحدث السيولات النشطة لحظياً
    active_queries = [
        "solana", "base", "ethereum", "bsc", "pump", 
        "ai", "meme", "pepe", "doge", "cat", "sol", "eth", "usdt"
    ]
    
    for q in active_queries:
        try:
            r = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={q}", timeout=2.5)
            if r.status_code == 200:
                data = r.json()
                items = data.get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items[:30])
        except Exception:
            pass

    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_surge_pair(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown").upper()
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    # فحص حجم التداول والزخم في آخر 5 دقائق (أقوى مؤشر للبمب السريع)
    volume = pair.get("volume", {})
    m5_vol = float(volume.get("m5", 0) or 0)
    h1_vol = float(volume.get("h1", 0) or 0)
    
    if m5_vol < MIN_VOLUME_5M:
        return

    price_change = pair.get("priceChange", {})
    m5_change = float(price_change.get("m5", 0) or 0)
    h1_change = float(price_change.get("h1", 0) or 0)

    # اشتراط أن تكون العملة في حالة اشتعال سعري (صعود في آخر 5 دقائق وساعة) بدون تأخير للقمم الميتة
    if m5_change <= 1.0 or h1_change > 300.0:
        return

    txns = pair.get("txns", {})
    m5 = txns.get("m5", {})
    m5_buys = m5.get("buys", 0) or 0
    m5_sells = m5.get("sells", 0) or 0

    # سيطرة واضحة لعمليات الشراء في آخر 5 دقائق
    if m5_buys <= m5_sells:
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

    status_text = f"🔥 بمب لحظي [5m: +{m5_change:.1f}%] [شراء 5m: {m5_buys} / بيع: {m5_sells}]"

    entry = {
        "type": "surge_spark",
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
        "strength": float(m5_vol * (1 + m5_change))
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"⚡ *رصد انفجار سيولة لحظي* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"حجم 5 دقائق: ${m5_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_instant_surge_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_surge_pair, p)
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
