"""
Elite True Zero-Lag Omni-Chain Sniper
رصد الصفقات والسيولة القوية مباشرة فور تأسيس العقد على جميع السلاسل
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

# ============ الإعدادات الاحترافية القصوى ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط سيولة حقيقية وقوية جداً لاستبعاد العملات الميتة أو الوهمية
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 3000))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 500))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 1.0))
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 300

app = FastAPI(title="Elite True Zero-Lag Sniper")

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


def get_elite_raw_pairs():
    """جلب أحدث أزواج التداول والسيولة مباشرة عبر عدة مسارات متوازية لتفادي التأخير"""
    pairs_list = []
    
    # 1. جلب أحدث الـ Token Profiles الخام
    try:
        r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=2)
        if r.status_code == 200:
            profiles = r.json()
            if isinstance(profiles, list):
                addresses = [p.get("tokenAddress") for p in profiles[:80] if p.get("tokenAddress")]
                if addresses:
                    # تقسيم الطلبات لضمان السرعة القصوى وعدم حصول Timeout
                    for i in range(0, len(addresses), 25):
                        chunk = addresses[i:i+25]
                        r_tok = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(chunk)}", timeout=2)
                        if r_tok.status_code == 200:
                            items = r_tok.json().get("pairs", [])
                            if isinstance(items, list):
                                pairs_list.extend(items)
    except Exception:
        pass

    # 2. جلب أحدث الـ Boosts السريعة
    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=2)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addresses = [b.get("tokenAddress") for b in boosts[:50] if b.get("tokenAddress")]
                if addresses:
                    r3 = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses)}", timeout=2)
                    if r3.status_code == 200:
                        p_data = r3.json().get("pairs", [])
                        if isinstance(p_data, list):
                            pairs_list.extend(p_data)
    except Exception:
        pass

    # 3. تغطية أحدث الرموز الأكثر تفاعلاً على جميع السلاسل
    hot_keywords = ["sol", "base", "eth", "bsc", "pump", "ai", "meme", "pepe", "sui", "arb", "doge"]
    for kw in hot_keywords:
        try:
            rq = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={kw}", timeout=2)
            if rq.status_code == 200:
                items = rq.json().get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items[:20])
        except Exception:
            pass

    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_elite_pair(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown").upper()
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    # اشتراط سيولة قوية وحقيقية تمنع دخول العملات الضعيفة
    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
    if h1_vol < MIN_VOLUME_USD:
        return

    price_change = pair.get("priceChange", {})
    h1_change = float(price_change.get("h1", 0) or 0)

    # القاعدة الاحترافية: العملة في مرحلة التأسيس المبكرة جداً (أقل من 35% صعود) لضمان عدم تفويت الانطلاقة
    if h1_change > 35.0:
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

    status_text = f"💎 قنص سيولة قوية ومبكرة [السيولة: ${liq_usd:,.0f}] [1h: {h1_change:+.1f}%]"

    entry = {
        "type": "elite_sniper",
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
        f"🎯 *قنص احترافي (سيولة قوية)* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"الحجم: ${h1_vol:,.0f} | السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_elite_raw_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_elite_pair, p)
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
