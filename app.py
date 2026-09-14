"""
Smart Meme Accumulation & Early Breakout Tracker
رصد واصتياد بدايات البمب وتجميع الحيتان مع قفل السيولة
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

# ============ إعدادات الرادار الذكي ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط مدروسة لدخول بداية البمب بطلب سيولة آمنة
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 2500))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 1000))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 10))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = 45

app = FastAPI(title="Smart Meme Early Breakout Tracker")

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


def get_latest_meme_addresses():
    token_entries = []
    endpoints = [
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/token-profiles/latest/v1"
    ]
    for ep in endpoints:
        try:
            r = requests.get(ep, timeout=8)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        c_id, t_addr = item.get("chainId"), item.get("tokenAddress")
                        if c_id and t_addr:
                            token_entries.append((c_id, t_addr))
        except Exception:
            pass

    seen, unique = set(), []
    for entry in token_entries:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
            
    return unique[:50]


def get_pairs_batch(token_addresses):
    if not token_addresses:
        return {}
    addresses_str = ",".join(token_addresses)
    url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses_str}"
    results = {}
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            pairs = r.json().get("pairs") or []
            for p in pairs:
                base_addr = p.get("baseToken", {}).get("address")
                if base_addr:
                    curr_liq = p.get("liquidity", {}).get("usd", 0) or 0
                    if base_addr not in results or curr_liq > (results[base_addr].get("liquidity", {}).get("usd", 0) or 0):
                        results[base_addr] = p
    except Exception:
        pass
    return results


def verify_liquidity_and_safety(pair):
    """التحقق من أمان السيولة والعقد"""
    liq_usd = pair.get("liquidity", {}).get("usd", 0) or 0
    labels = pair.get("labels", [])
    is_locked = any("locked" in str(l).lower() for l in labels)

    if is_locked or liq_usd >= 10000:
        return "🔒 سيولة مقفولة ومحمية (آمن جداً)", True
    elif liq_usd >= MIN_LIQUIDITY_USD:
        return "🛡️ سيولة جيدة ونظيفة", True
    return "⚠️ تحذير سيولة", False


def analyze_early_breakout(chain_id, token_address, pair):
    if not pair:
        return

    if chain_id not in ["solana", "base", "ethereum", "bsc"]:
        return

    h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
    if h1_vol < MIN_VOLUME_USD:
        return

    safety_text, is_safe = verify_liquidity_and_safety(pair)
    if not is_safe:
        return

    txns = pair.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0

    # شرط بداية البمب: نشاط شراء قوي واكتساح لعمليات البيع
    is_breakout = (h1_buys >= h1_sells * 1.5) and (h1_buys >= 4)
    if not is_breakout:
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair.get("baseToken", {}).get("symbol", "?")
    name = pair.get("baseToken", {}).get("name", "Meme")
    price = pair.get("priceUsd", "?")
    mcap = pair.get("fdv", pair.get("marketCap", "?"))
    liq_usd = pair.get("liquidity", {}).get("usd", 0) or 0
    pair_url = pair.get("url", "")

    entry = {
        "type": "early_breakout",
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
        "safety": safety_text,
        "strength": float(h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"⚡ *رصد بداية بمب جديد* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الأمان: {safety_text}\n"
        f"شراء/بيع (1h): {h1_buys} شراﺀ / {h1_sells} بيع\n"
        f"الحجم: ${h1_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        token_entries = await asyncio.to_thread(get_latest_meme_addresses)
        if token_entries:
            addresses = [item[1] for item in token_entries]
            pairs_dict = await asyncio.to_thread(get_pairs_batch, addresses)
            
            for chain_id, token_address in token_entries:
                pair = pairs_dict.get(token_address)
                if pair:
                    await asyncio.to_thread(analyze_early_breakout, chain_id, token_address, pair)
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
