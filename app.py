"""
Meme Coins Multi-Wallet Accumulation Tracker
رصد واصتياد تجميع الميمز والشراء القوي من محافظ متعددة
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

# ============ إعدادات ميمز ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط مخصصة للميمز الباحثة عن الانفجار
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 1500))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 800))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 5))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = 60

app = FastAPI(title="Meme Coins Accumulation Tracker")

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


def get_meme_market_pairs():
    """البحث المباشر واستخراج أزواج وحركات الميمز الحية"""
    pairs_list = []
    # استعلامات بحث تركز على منصات وشبكات الميمز الشهيرة (مثل Pump.fun, Solana, Base, ETH)
    queries = ["pump", "meme", "doge", "pepe", "cat", "SOL", "BASE"]
    
    for q in queries:
        url = f"https://api.dexscreener.com/latest/dex/search?q={q}"
        try:
            r = requests.get(url, timeout=6)
            if r.status_code == 200:
                data = r.json()
                items = data.get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items)
        except Exception:
            pass

    # فلترة المتكرر
    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
    
    return unique


def analyze_meme_accumulation(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown")
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    # التأكد أن الزوج يخص شبكات حركة الميمز الشهيرة
    if chain_id not in ["solana", "base", "ethereum", "bsc"]:
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

    # شروط التجميع القوي واحتفاظ الحيتان (عمليات شراء أعلى بوضوح من البيع)
    is_meme_accumulation = (h1_buys >= h1_sells * 1.3) and (h1_buys >= 4)

    if not is_meme_accumulation:
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair.get("baseToken", {}).get("symbol", "?")
    name = pair.get("baseToken", {}).get("name", "Meme Coin")
    price = pair.get("priceUsd", "?")
    mcap = pair.get("fdv", pair.get("marketCap", "?"))
    pair_url = pair.get("url", "")

    entry = {
        "type": "meme_accumulation",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "name": name,
        "token_address": token_address,
        "price": price,
        "mcap": mcap,
        "liquidity": liq,
        "volume": h1_vol,
        "buys": h1_buys,
        "sells": h1_sells,
        "url": pair_url,
        "safety": f"🐸 ميم آمن (${liq:,.0f})",
        "strength": float(h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🐸 *تجميع ميم قوي* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"شراء/بيع (1h): {h1_buys} شراﺀ / {h1_sells} بيع\n"
        f"حجم التداول: ${h1_vol:,.0f} | الماركت كاب: ${mcap}\n"
        f"السيولة: ${liq:,.0f}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_meme_market_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_meme_accumulation, p)
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
