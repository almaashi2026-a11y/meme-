"""
Multi-Wallet Accumulation & Retention Tracker
رصد الشراء القوي من محافظ متعددة والاحتفاظ بها في البداية المبكرة.
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

# ============ الإعدادات ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 4000))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 2500))

TRENDING_REFRESH_SECONDS = 45
TX_POLL_SECONDS = float(os.environ.get("TX_POLL_SECONDS", 5))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = 120

app = FastAPI(title="Multi-Wallet Accumulation Tracker")

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


def get_latest_dex_pairs():
    tokens = []
    endpoints = [
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/token-profiles/latest/v1"
    ]
    for ep in endpoints:
        try:
            r = requests.get(ep, timeout=8)
            if r.status_code == 200:
                data = r.json()
                for item in data if isinstance(data, list) else []:
                    c_id, t_addr = item.get("chainId"), item.get("tokenAddress")
                    if c_id and t_addr:
                        tokens.append((c_id, t_addr))
        except Exception:
            pass

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


def analyze_multi_wallet_accumulation(chain_id, token_address, pair_data):
    if not pair_data:
        return

    liq = float(pair_data.get("liquidity", {}).get("usd", 0) or 0)
    if liq < MIN_LIQUIDITY_USD:
        return

    txns = pair_data.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0
    h1_vol = pair_data.get("volume", {}).get("h1", 0) or 0

    if h1_vol < MIN_VOLUME_USD:
        return

    # الشرط الاحترافي: عمليات شراء قوية من عدة محافظ (شراء عالي مقارنة بالبيع واحتفاظ)
    is_strong_accumulation = (h1_buys >= h1_sells * 1.5) and (h1_buys >= 5)

    if not is_strong_accumulation:
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair_data.get("baseToken", {}).get("symbol", "?")
    price = pair_data.get("priceUsd", "?")
    mcap = pair_data.get("fdv", pair_data.get("marketCap", "?"))
    pair_url = pair_data.get("url", "")

    entry = {
        "type": "multi_wallet_accumulation",
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
        "safety": f"🛡️ سيولة آمنة (${liq:,.0f})",
        "strength": float(h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🐋 *Multi-Wallet Accumulation* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}* (شراء قوي واحتفاظ)\n"
        f"العقد: `{token_address}`\n"
        f"العمليات (شراء/بيع 1h): {h1_buys} شراﺀ / {h1_sells} بيع\n"
        f"حجم التداول: ${h1_vol:,.0f}\n"
        f"السعر: ${price}\n"
        f"Liquidity: ${liq:,.0f}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    trending = []
    last_refresh = 0
    while True:
        now = time.time()
        if now - last_refresh >= TRENDING_REFRESH_SECONDS:
            trending = await asyncio.to_thread(get_latest_dex_pairs)
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
                        await asyncio.to_thread(analyze_multi_wallet_accumulation, chain_id, token_address, pair_data)
                        stats["scanned_tokens"] += 1

                await asyncio.sleep(1.0)

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
