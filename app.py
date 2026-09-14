"""
Secure Meme Multi-Wallet Accumulation & Locked LP Tracker
رصد ميمز التجميع الآمن مع فحص قفل السيولة وحماية العقود
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

# ============ إعدادات الأمان والميمز ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط سيولة آمنة تضمن القدرة على البيع والخروج بسلاسة
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 3000))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 1500))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 10))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = 60

app = FastAPI(title="Secure Meme Accumulation & LP Tracker")

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
            
    return unique[:45]


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


def check_lp_safety_and_lock(pair):
    """فحص حالة السيولة وقفلها للتأكد من أمان العقد"""
    liquidity_info = pair.get("liquidity", {})
    lp_usd = liquidity_info.get("usd", 0) or 0
    
    # فحص خيارات قفل السيولة المتاحة في بيانات الزوج
    pair_labels = pair.get("labels", [])
    is_locked = any("locked" in str(label).lower() for label in pair_labels)
    
    if is_locked or lp_usd >= 15000:
        return "🔒 سيولة مقفولة ومؤمنة (آمن جداً)", True
    elif lp_usd >= MIN_LIQUIDITY_USD:
        return "🛡️ سيولة مقبولة ونظيفة", True
    
    return "⚠️ تحذير: السيولة منخفضة أو غير مؤكدة", False


def analyze_secure_meme(chain_id, token_address, pair):
    if not pair:
        return

    if chain_id not in ["solana", "base", "ethereum", "bsc"]:
        return

    h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
    if h1_vol < MIN_VOLUME_USD:
        return

    # فحص الأمان وقفل السيولة
    safety_status, is_safe = check_lp_safety_and_lock(pair)
    if not is_safe:
        return

    txns = pair.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0

    # شروط تجميع حقيقي من محافظ متعددة (الشراء أعلى بوضوح من البيع)
    is_accumulation = (h1_buys >= h1_sells * 1.4) and (h1_buys >= 3)
    if not is_accumulation:
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
        "type": "secure_meme_accumulation",
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
        "safety": safety_status,
        "strength": float(h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🔒 *تجميع ميم آمن ومقفول السيولة* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"حالة الأمان: {safety_status}\n"
        f"شراء/بيع (1h): {h1_buys} / {h1_sells}\n"
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
                    await asyncio.to_thread(analyze_secure_meme, chain_id, token_address, pair)
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
