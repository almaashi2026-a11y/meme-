"""
Cross-Chain & Robinhood Meme Liquidity Flow Tracker
تتبع تدفق السيولة وحجم الشراء القوي عبر شبكة روبن هود وجميع الشبكات
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

# ============ الإعدادات والشاملة لشبكة روبن هود والشبكات الأخرى ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 2000))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 1000))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 10))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = 45

app = FastAPI(title="Cross-Chain & Robinhood Flow Tracker")

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


def get_cross_chain_market_tokens():
    """جلب أحدث التوكنات والسيولة النشطة وتشمل شبكة روبن هود والشبكات الكبرى"""
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
                        c_id = item.get("chainId")
                        t_addr = item.get("tokenAddress")
                        if c_id and t_addr:
                            token_entries.append((c_id.lower(), t_addr))
        except Exception:
            pass

    seen, unique = set(), []
    for entry in token_entries:
        if entry not in seen:
            seen.add(entry)
            unique.append(entry)
            
    return unique[:60]


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


def analyze_cross_chain_flow(chain_id, token_address, pair):
    if not pair:
        return

    # إعطاء الأولوية القصوى والتركيز على شبكة روبن هود والشبكات الشهيرة
    target_chains = ["robinhood", "arbitrum", "solana", "base", "ethereum", "bsc"]
    if chain_id not in target_chains and "robinhood" not in chain_id:
        # نسمح بقبول الشبكات العامة أيضاً لضمان عدم تفويت أي فرصة قوية
        pass

    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
    if h1_vol < MIN_VOLUME_USD:
        return

    txns = pair.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0

    buy_pressure_ratio = (h1_buys / max(h1_sells, 1))
    
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

    is_robinhood = "robinhood" in chain_id
    network_tag = "🎯 [شبكة روبن هود - Robinhood]" if is_robinhood else f"🌐 [{chain_id.upper()}]"

    flow_status = f"🌊 تدفق قوي [شراء: {h1_buys} | بيع: {h1_sells}] - نسبة {buy_pressure_ratio:.1f}x"

    entry = {
        "type": "robinhood_cross_flow",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id.upper(),
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
        "safety": flow_status,
        "strength": float(h1_vol * buy_pressure_ratio * (2.0 if is_robinhood else 1.0))
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🚀 *تدفق سيولة وشراء قوي* {network_tag}\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"حالة التدفق: {flow_status}\n"
        f"حجم التداول (1h): ${h1_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        token_entries = await asyncio.to_thread(get_cross_chain_market_tokens)
        if token_entries:
            addresses = [item[1] for item in token_entries]
            pairs_dict = await asyncio.to_thread(get_pairs_batch, addresses)
            
            for chain_id, token_address in token_entries:
                pair = pairs_dict.get(token_address)
                if pair:
                    await asyncio.to_thread(analyze_cross_chain_flow, chain_id, token_address, pair)
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
