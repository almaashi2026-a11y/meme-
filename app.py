"""
Hyper-Speed Zero-Lag Omni-Chain Radar
رصد فائق السرعة وبدون أي تأخير لجميع العقود لحظة ولادتها على البلوكتشين
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

# ============ إعدادات السرعة القصوى (بدون تأخير) ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط مرنة للغاية لضمان عدم ضياع أي فرصة مبكرة
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 50))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 10))

# سرعة فحص خارقة كل نصف ثانية فقط!
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 0.5))
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 180

app = FastAPI(title="Hyper-Speed Zero-Lag Radar")

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


def get_hyper_speed_pairs():
    """جلب أحدث الأزواج بأقصى سرعة ممكنة عبر مصادر متعددة بالتوازي"""
    pairs_list = []
    
    # 1. أحدث الـ Token Profiles مباشرة
    try:
        r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=1.5)
        if r.status_code == 200:
            profiles = r.json()
            if isinstance(profiles, list):
                addresses = [p.get("tokenAddress") for p in profiles[:80] if p.get("tokenAddress")]
                if addresses:
                    r_tok = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses[:30])}", timeout=1.5)
                    if r_tok.status_code == 200:
                        items = r_tok.json().get("pairs", [])
                        if isinstance(items, list):
                            pairs_list.extend(items)
    except Exception:
        pass

    # 2. أحدث الـ Token Boosts مباشرة
    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=1.5)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addresses = [b.get("tokenAddress") for b in boosts[:80] if b.get("tokenAddress")]
                if addresses:
                    r3 = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses[:30])}", timeout=1.5)
                    if r3.status_code == 200:
                        p_data = r3.json().get("pairs", [])
                        if isinstance(p_data, list):
                            pairs_list.extend(p_data)
    except Exception:
        pass

    # 3. استعلامات سريعة جداً لأحدث الكلمات الدالة في كل السلاسل
    quick_queries = ["sol", "base", "eth", "pump", "ai", "meme", "pepe", "doge", "bsc", "sui"]
    for q in quick_queries:
        try:
            rq = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={q}", timeout=1.5)
            if rq.status_code == 200:
                items = rq.json().get("pairs", [])
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


def analyze_hyper_pair(pair):
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

    # إلغاء قيود الصعود الصارمة لكي نلتقط العملة قبل أن يتحدث السعر ويطير
    if h1_change > 300.0:
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

    status_text = f"⚡ رصد فائق السرعة [1h: {h1_change:+.1f}%] [سيولة: ${liq_usd:,.0f}]"

    entry = {
        "type": "hyper_spark",
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
        f"🚀 *رصد قنص فائق السرعة* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"الحجم: ${h1_vol:,.0f} | السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_hyper_speed_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_hyper_pair, p)
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
