"""
Ultra-Realtime New Pairs & Whale Buy Radar
رصد لحظي فوري للتوكنات الجديدة وصفقات الحيتان أثناء الدخول عبر جميع السلاسل
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

# ============ إعدادات الرصد اللحظي الفوري ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط مرنة وسريعة لالتقاط العملة من ثوانيها الأولى
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 800))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 300))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 3))  # فحص سريع جداً كل 3 ثوانٍ
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 20  # تكرار مسموح أسرع لضمان متابعة الزخم

app = FastAPI(title="Ultra-Realtime Whale & New Pair Radar")

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
        }, timeout=5)
    except Exception:
        pass


def get_latest_created_pairs():
    """جلب أحدث الأزواج والتوكنات التي تم إطلاقها للتو في السوق عبر جميع السلاسل"""
    pairs_list = []
    
    # نقاط النهاية الخاصة بأحدث العملات المضافة والنشطة لحظياً في DEXScreener
    endpoints = [
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/latest/dex/search?q=pump",
        "https://api.dexscreener.com/latest/dex/search?q=sol",
        "https://api.dexscreener.com/latest/dex/search?q=eth"
    ]
    
    for ep in endpoints:
        try:
            r = requests.get(ep, timeout=4)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    # إذا كانت قائمة بـ boosts
                    addresses = [item.get("tokenAddress") for item in data if item.get("tokenAddress")]
                    if addresses:
                        r_tokens = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses[:30])}", timeout=4)
                        if r_tokens.status_code == 200:
                            p_data = r_tokens.json().get("pairs", [])
                            if isinstance(p_data, list):
                                pairs_list.extend(p_data)
                elif isinstance(data, dict):
                    items = data.get("pairs", [])
                    if isinstance(items, list):
                        pairs_list.extend(items)
        except Exception:
            pass

    # إزالة التكرار بدقة تامة
    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_realtime_whale_entry(pair):
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

    txns = pair.get("txns", {})
    # نركز على المعاملات اللحظية (5 دقائق إن وجدت أو الساعة الأولى) لالتقاط الدخول المبكر جداً
    m5 = txns.get("m5", {})
    m5_buys = m5.get("buys", 0) or 0
    m5_sells = m5.get("sells", 0) or 0

    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0

    # شرط الدخول اللحظي: هجوم شراء قوي في آخر 5 دقائق أو ضغط شراء كاسح
    is_active_m5 = (m5_buys >= 2 and m5_buys >= m5_sells)
    is_strong_h1 = (h1_buys > h1_sells * 1.2)

    if not is_active_m5 and not is_strong_h1:
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

    status_text = f"⚡ دخول حيتان لحظي [5m شراء: {m5_buys} | بيع: {m5_sells}] (1h شراء: {h1_buys})"

    entry = {
        "type": "realtime_whale_entry",
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
        "strength": float(h1_vol + (m5_buys * 1000))
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🚨 *رصد دخول صفقات حيتان فورية* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"حجم التداول: ${h1_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(get_latest_created_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_realtime_whale_entry, p)
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
