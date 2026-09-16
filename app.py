"""
Omni-Chain Real-Time New Pairs Radar
رصد فوري لحظي لجميع الشبكات واصطياد العملات فور انطلاقها والشمعة الأولى
"""

import asyncio
import time
import os
from collections import deque
from datetime import datetime, timezone

import requests
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles:: StaticFiles if False else StaticFiles  # للضمان النحوي
from fastapi.staticfiles import StaticFiles

# ============ إعدادات الشمولية لجميع الشبكات ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 300))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 50))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 1.5))
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 180

app = FastAPI(title="Omni-Chain Real-Time Radar")

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
        }, timeout=4)
    except Exception:
        pass


def get_omni_chain_new_pairs():
    """جلب أحدث العملات والملفات والبوستات لجميع الشبكات عالمياً"""
    pairs_list = []
    
    # 1. أحدث الـ Token Profiles عبر جميع الشبكات
    try:
        r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=3)
        if r.status_code == 200:
            profiles = r.json()
            if isinstance(profiles, list):
                addresses = [p.get("tokenAddress") for p in profiles[:50] if p.get("tokenAddress")]
                if addresses:
                    r_tok = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses)}", timeout=3)
                    if r_tok.status_code == 200:
                        items = r_tok.json().get("pairs", [])
                        if isinstance(items, list):
                            pairs_list.extend(items)
    except Exception:
        pass

    # 2. أحدث الـ Token Boosts عبر جميع الشبكات
    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=3)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addresses = [b.get("tokenAddress") for b in boosts[:50] if b.get("tokenAddress")]
                if addresses:
                    r3 = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses)}", timeout=3)
                    if r3.status_code == 200:
                        p_data = r3.json().get("pairs", [])
                        if isinstance(p_data, list):
                            pairs_list.extend(p_data)
    except Exception:
        pass

    # 3. تغطية شاملة لجميع الشبكات عبر استعلامات متعددة ومتنوعة
    omni_queries = [
        "solana", "base", "ethereum", "bsc", "arbitrum", 
        "polygon", "avalanche", "sui", "optimism", "pump", "inu", "pepe", "ai"
    ]
    for q in omni_queries:
        try:
            r_q = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={q}", timeout=3)
            if r_q.status_code == 200:
                items = r_q.json().get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items[:15])
        except Exception:
            pass

    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_omni_pair(pair):
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

    # السماح بالعملات الجديدة كلياً بشرط عدم تجاوز حد القمم الكبيرة المتأخرة
    if h1_change > 150.0:
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

    status_text = f"🌐 رصد شامل لجميع الشبكات [1h: +{h1_change:.1f}%] (شراء 5m: {m5_buys})"

    entry = {
        "type": "omni_spark",
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
        f"🎯 *رصد عملة جديدة [شبكة: {chain_id}]*\n"
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
        pairs = await asyncio.to_thread(get_omni_chain_new_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_omni_pair, p)
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
