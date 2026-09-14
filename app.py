"""
Live Real-Time Market Feed Tracker - Instant Accumulation
رصد حي ومباشر لأحدث الأزواج والتجميع اللحظي بدون تأخير.
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

# ============ الإعدادات المباشرة ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط مرنة جداً لضمان ظهور العملات الحية مباشرة على الداشبورد
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 2000))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 1000))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 5))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = 60

app = FastAPI(title="Live Real-Time Market Feed Tracker")

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
        }, timeout=8)
    except Exception:
        pass


def get_live_market_pairs():
    """جلب أحدث أزواج التداول الحية مباشرة من السوق"""
    pairs_list = []
    # نعتمد على البحث العام أو الروابط المباشرة لأحدث الأزواج النشطة
    urls = [
        "https://api.dexscreener.com/latest/dex/search?q=SOL",
        "https://api.dexscreener.com/latest/dex/search?q=ETH",
        "https://api.dexscreener.com/latest/dex/search?q=USDT"
    ]
    
    for url in urls:
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                data = r.json()
                items = data.get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items)
        except Exception:
            pass

    # تصفية الأزواج المتكررة حسب العنوان
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

    chain_id = pair.get("chainId", "unknown")
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    liq = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq < MIN_LIQUIDITY_USD:
        return

    h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
    if h1_vol < MIN_VOLUME_USD:
        return

    txns = pair.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0

    # شرط تجميع ومشترين نشطين
    if h1_buys < h1_sells and h1_buys < 3:
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair.get("baseToken", {}).get("symbol", "?")
    price = pair.get("priceUsd", "?")
    mcap = pair.get("fdv", pair.get("marketCap", "?"))
    pair_url = pair.get("url", "")

    entry = {
        "type": "live_accumulation",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "token_address": token_address,
        "price": price,
        "mcap": mcap,
        "liquidity": liq,
        "volume": h1_vol,
        "buys": h1_buys,
        "sells": h1_sells,
        "url": pair_url,
        "safety": f"🛡️ سيولة (${liq:,.0f})",
        "strength": float(h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"⚡ *Live Accumulation* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}*\n"
        f"العقد: `{token_address}`\n"
        f"شراء/بيع (1h): {h1_buys} / {h1_sells}\n"
        f"الحجم: ${h1_vol:,.0f} | السعر: ${price}\n"
        f"Liquidity: ${liq:,.0f}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_live_market_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_and_push, p)
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
