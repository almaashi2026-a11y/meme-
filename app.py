"""
Smart Pro Wallet Accumulation & Early Entry Radar
رصد احترافي متقدم لدخول المحافظ والسيولة في بداية العقود عبر جميع السلاسل
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

# ============ إعدادات الرصد الاحترافي للمحافظ ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط متوازنة لضمان جودة السيولة وعدم الدخول في عملات ميتة
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 1500))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 600))

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 3))
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 60

app = FastAPI(title="Smart Wallet Accumulation Radar")

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


def get_smart_wallet_pairs():
    """جلب أزواج العملات والتوكنات النشطة التي تتعرض لضخ سيولة جديد"""
    pairs_list = []
    
    queries = ["pump", "sol", "base", "ai", "meme", "inu", "pepe", "cat", "doge", "eth"]
    for q in queries:
        url = f"https://api.dexscreener.com/latest/dex/search?q={q}"
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                data = r.json()
                items = data.get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items)
        except Exception:
            pass

    # إضافة أحدث الـ Boosts لالتقاط المشاريع الجديدة فور طرحها
    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=4)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addresses = [b.get("tokenAddress") for b in boosts[:30] if b.get("tokenAddress")]
                if addresses:
                    r3 = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addresses)}", timeout=4)
                    if r3.status_code == 200:
                        p_data = r3.json().get("pairs", [])
                        if isinstance(p_data, list):
                            pairs_list.extend(p_data)
    except Exception:
                        pass

    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_smart_wallet_entry(pair):
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

    # نسب التغير السعري (لمنع الدخول في القمم المتأخرة)
    price_change = pair.get("priceChange", {})
    h1_change = float(price_change.get("h1", 0) or 0)
    m5_change = float(price_change.get("m5", 0) or 0)

    # القاعدة الذهبية للاحتراف: الصعود يجب أن يكون في بدايته (بين 1.5% إلى 35% فقط)
    # أي عملة صاعدة بأكثر من 35% في الساعة تُستبعد تماماً لتفادي الهبوط والقمم.
    if h1_change < 1.5 or h1_change > 35.0:
        return

    txns = pair.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0) or 0
    h1_sells = txns.get("sells", {}).get("h1", 0) or 0

    # اشتراط تفوق واضح للمشترين (ضغط شراء المحافظ)
    if h1_buys < h1_sells * 1.5 or h1_buys < 5:
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

    status_text = f"🐋 رصد دخول محافظ [صعود: +{h1_change:.1f}%] (شراء: {h1_buys} | بيع: {h1_sells})"

    entry = {
        "type": "smart_wallet_entry",
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
        "strength": float(h1_vol * (1 + h1_change))
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🎯 *رصد دخول محافظ مبكر* [{chain_id}]\n"
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
        pairs = await asyncio.to_thread(get_smart_wallet_pairs)
        if pairs:
            for p in pairs:
                await asyncio.to_thread(analyze_smart_wallet_entry, p)
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
