"""
Omni-Chain Smart Accumulation & Strong Buy Tracker
مسح شامل لجميع سلاسل البلوكتشين ورصد تدفق الشراء القوي
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

# ============ إعدادات المسح الشامل لجميع السلاسل ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 2500))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 1000))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 8))
MAX_ALERTS_STORED = 400
ALERT_COOLDOWN_SECONDS = 60

app = FastAPI(title="Omni-Chain Strong Buy Tracker")

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


def get_omni_chain_market_pairs():
    """جلب أزواج العملات والترندات من جميع سلاسل السوق بلا استثناء"""
    pairs_list = []
    
    # استعلامات متنوعة لأهم الكلمات والرموز لجلب أوسع نطاق ممكن عبر كل الشبكات
    search_terms = [
        "SOL", "ETH", "BSC", "ARB", "BASE", "POL", "AVAX", "FTM", 
        "PEPE", "DOGE", "SHIB", "AI", "MEME", "CAT", "PUMP", "MOON", "INU", "USD"
    ]
    
    for term in search_terms:
        url = f"https://api.dexscreener.com/latest/dex/search?q={term}"
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                data = r.json()
                items = data.get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items)
        except Exception:
            pass

    # جلب أحدث الـ Boosts والـ Profiles عبر كل الشبكات
    endpoints = [
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/token-profiles/latest/v1"
    ]
    for ep in endpoints:
        try:
            r = requests.get(ep, timeout=5)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    addresses = [item.get("tokenAddress") for item in data if item.get("tokenAddress")]
                    if addresses:
                        r_tokens = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses[:30])}", timeout=5)
                        if r_tokens.status_code == 200:
                            p_data = r_tokens.json().get("pairs", [])
                            if isinstance(p_data, list):
                                pairs_list.extend(p_data)
        except Exception:
            pass

    # إزالة التكرار بدقة عالية بناءً على عنوان العقد
    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_omni_chain(pair):
    if not pair:
        return

    # دعم أي سلسلة بلوكتشين في العالم دون استثناء
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

    txns = pair.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0

    # شرط الشراء القوي (المشترين يغلبون البائعين بوضوح)
    if h1_buys < h1_sells * 1.3 or h1_buys < 4:
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

    buy_ratio = (h1_buys / max(h1_sells, 1))
    status_text = f"🌐 تدفق سيولة هائل [شراء: {h1_buys} | بيع: {h1_sells}] - نسبة {buy_ratio:.1f}x"

    entry = {
        "type": "omni_chain_flow",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
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
        "strength": float(h1_vol * buy_ratio)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🚀 *رصد شراء قوي عبر السلاسل* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"الحجم (1h): ${h1_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_omni_chain_market_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_omni_chain, p)
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
