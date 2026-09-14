"""
Instant Direct Feed Tracker - Simple & Fast Entry
رصد مباشر وفوري للعملات والسيولة بدون تعقيد لضمان ظهور النتائج فوراً.
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

# ============ الإعدادات المبسطة ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 1000)) # حد أدنى مرن للسيولة
TRENDING_REFRESH_SECONDS = 45
TX_POLL_SECONDS = float(os.environ.get("TX_POLL_SECONDS", 4))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = 60

app = FastAPI(title="Instant Direct Feed Tracker")

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
        }, timeout=10)
    except Exception:
        pass


def get_trending_tokens():
    tokens = []
    # جلب العملات المدعومة والجديدة
    for endpoint in [
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/token-profiles/latest/v1"
    ]:
        try:
            r = requests.get(endpoint, timeout=8)
            if r.status_code == 200:
                data = r.json()
                for item in data if isinstance(data, list) else []:
                    c_id, t_addr = item.get("chainId"), item.get("tokenAddress")
                    if c_id and t_addr:
                        tokens.append((c_id, t_addr))
        except Exception:
            pass
    
    # تصفية التكرار
    seen, unique = set(), []
    for k in tokens:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique


def get_pairs_data_batch(token_addresses):
    if not token_addresses:
        return {}
    addresses_str = ",".join(token_addresses[:35])
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


def process_token_pair(chain_id, token_address, pair_data):
    if not pair_data:
        return

    liq = float(pair_data.get("liquidity", {}).get("usd", 0) or 0)
    if liq < MIN_LIQUIDITY_USD:
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair_data.get("baseToken", {}).get("symbol", "?")
    price = pair_data.get("priceUsd", "?")
    mcap = pair_data.get("fdv", pair_data.get("marketCap", "?"))
    pair_url = pair_data.get("url", "")
    
    volume = pair_data.get("volume", {}).get("h1", 0) or 0

    entry = {
        "type": "direct_feed",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "token_address": token_address,
        "price": price,
        "mcap": mcap,
        "liquidity": liq,
        "volume": volume,
        "url": pair_url,
        "safety": "🛡️ عقد مرصود (جاهز)",
        "strength": float(liq)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🚀 *New Active Token* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}*\n"
        f"العقد: `{token_address}`\n"
        f"السعر: ${price}\n"
        f"Liquidity: ${liq:,.0f}\n"
        f"Volume (1h): ${volume:,.0f}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    trending = []
    last_refresh = 0
    while True:
        now = time.time()
        if now - last_refresh >= TRENDING_REFRESH_SECONDS:
            trending = await asyncio.to_thread(get_trending_tokens)
            last_refresh = now

        if trending:
            chunk_size = 35
            for i in range(0, len(trending), chunk_size):
                chunk = trending[i:i + chunk_size]
                token_addresses = [item[1] for item in chunk]
                
                pairs_dict = await asyncio.to_thread(get_pairs_data_batch, token_addresses)

                for chain_id, token_address in chunk:
                    pair_data = pairs_dict.get(token_address)
                    if pair_data:
                        await asyncio.to_thread(process_token_pair, chain_id, token_address, pair_data)
                        stats["scanned_tokens"] += 1

                await asyncio.sleep(0.5)

        stats["last_scan"] = datetime.now(timezone.utc).isoformat()
        await asyncio.sleep(TX_POLL_SECONDS)


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
