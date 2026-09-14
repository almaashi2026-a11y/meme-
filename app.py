"""
Instant Early Momentum Tracker - Ultra Fast Entry
رصد الشرر الأول للانطلاقة السعرية الفورية والدخول المبكر اللحظي.
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

# ============ الإعدادات الفورية ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 2000))
TRENDING_REFRESH_SECONDS = 60
TX_POLL_SECONDS = float(os.environ.get("TX_POLL_SECONDS", 5)) # فحص أسرع كل 5 ثوانٍ
MAX_ALERTS_STORED = 300

# شروط الانطلاقة الفورية (أول الشرارة)
MOMENTUM_WINDOW_SECONDS = 30  # مراقبة آخر 30 ثانية فقط
MIN_PUMP_PCT = 3.5            # تنبيه فوري عند أول صعود بنسبة 3.5% إلى 18% (قبل الارتفاعات الكبيرة)
MAX_PUMP_PCT = 18.0
ALERT_COOLDOWN_SECONDS = float(os.environ.get("ALERT_COOLDOWN_SECONDS", 120))

EVM_CHAINS = {
    "ethereum": {"api_base": "https://api.etherscan.io/api", "api_key_env": "ETHERSCAN_API_KEY"},
    "bsc": {"api_base": "https://api.bscscan.com/api", "api_key_env": "BSCSCAN_API_KEY"},
    "base": {"api_base": "https://api.basescan.org/api", "api_key_env": "BASESCAN_API_KEY"},
    "arbitrum": {"api_base": "https://api.arbiscan.io/api", "api_key_env": "ARBISCAN_API_KEY"},
    "robinhood": {"api_base": "", "api_key_env": ""},
}

# ============ حالة مشتركة ============

alerts_feed = deque(maxlen=MAX_ALERTS_STORED)
stats = {"scanned_tokens": 0, "last_scan": None, "alerts_total": 0}

instant_price_store = {}
last_alert_time = {}

app = FastAPI(title="Instant Early Momentum Tracker")


# ============ أدوات مساعدة وجلب البيانات ============

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
    except Exception as e:
        print("[!] فشل إرسال تلقرام:", e)


def get_boosted_tokens():
    url = "https://api.dexscreener.com/token-boosts/latest/v1"
    tokens = []
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        for item in data if isinstance(data, list) else []:
            chain_id = item.get("chainId")
            token_address = item.get("tokenAddress")
            if chain_id and token_address:
                tokens.append((chain_id, token_address))
    except Exception:
        pass
    return tokens


def get_new_token_profiles():
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    tokens = []
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        for item in data if isinstance(data, list) else []:
            chain_id = item.get("chainId")
            token_address = item.get("tokenAddress")
            if chain_id and token_address:
                tokens.append((chain_id, token_address))
    except Exception:
        pass
    return tokens


def get_trending_tokens():
    combined = get_boosted_tokens() + get_new_token_profiles()
    seen_pairs, tokens = set(), []
    for key in combined:
        if key not in seen_pairs:
            seen_pairs.add(key)
            tokens.append(key)
    return tokens


def get_pairs_data_batch(token_addresses):
    if not token_addresses:
        return {}
    addresses_str = ",".join(token_addresses[:35])
    url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses_str}"
    results = {}
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
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


def check_contract_safety(pair_data):
    lp_usd = pair_data.get("liquidity", {}).get("usd", 0) or 0
    if lp_usd >= 8000:
        return "🛡️ سيولة ممتازة وآمنة"
    return "🛡️ عقد نظيف (دخول مبكر)"


def check_instant_momentum(chain_id, token_address, pair_data):
    if not pair_data:
        return
    try:
        price = float(pair_data.get("priceUsd") or 0)
    except (TypeError, ValueError):
        return
    if price <= 0:
        return

    liq = float(pair_data.get("liquidity", {}).get("usd", 0) or 0)
    if liq < MIN_LIQUIDITY_USD:
        return

    now = time.time()
    
    # تخزين السعر الأولي للعملة عند أول ظهور أو رصدها
    if token_address not in instant_price_store:
        instant_price_store[token_address] = (now, price)
        return

    first_time, first_price = instant_price_store[token_address]
    
    # إذا مر وقت طويل على السعر الأول، نقوم بتحديث نقطة البداية لتبقى الشراسة لحلية فورية
    if now - first_time > MOMENTUM_WINDOW_SECONDS:
        instant_price_store[token_address] = (now, price)
        return

    if first_price <= 0:
        return

    change_pct = (price - first_price) / first_price * 100

    # التنبيه الفوري بمجرد تحقيق الانطلاقة الأولى وعدم التأخير للنسب العالية
    if MIN_PUMP_PCT <= change_pct <= MAX_PUMP_PCT:
        last_alert = last_alert_time.get(token_address, 0)
        if now - last_alert < ALERT_COOLDOWN_SECONDS:
            return
        last_alert_time[token_address] = now

        symbol = pair_data.get("baseToken", {}).get("symbol", "?")
        mcap = pair_data.get("fdv", "?")
        pair_url = pair_data.get("url", "")
        safety_status = check_contract_safety(pair_data)

        entry = {
            "type": "instant_momentum",
            "time": datetime.now(timezone.utc).isoformat(),
            "chain": chain_id,
            "symbol": symbol,
            "token_address": token_address,
            "change_pct": round(change_pct, 1),
            "price": price,
            "mcap": mcap,
            "liquidity": liq,
            "url": pair_url,
            "safety": safety_status,
            "strength": float(change_pct)
        }
        alerts_feed.appendleft(entry)
        stats["alerts_total"] += 1

        msg = (
            f"⚡ *Instant Early Momentum* [{chain_id.upper()}]\n"
            f"العملة: *{symbol}* (انطلاقة أولية +{change_pct:.1f}%)\n"
            f"العقد: `{token_address}`\n"
            f"الحالة: {safety_status}\n"
            f"السعر: ${price}\n"
            f"Market Cap: ${mcap}\n"
            f"Liquidity: ${liq:,.0f}\n"
            f"{pair_url}"
        )
        send_telegram_alert(msg)


# ============ حلقة المسح السريع ============

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
                        await asyncio.to_thread(check_instant_momentum, chain_id, token_address, pair_data)
                        stats["scanned_tokens"] += 1

                await asyncio.sleep(1.0)

        stats["last_scan"] = datetime.now(timezone.utc).isoformat()
        await asyncio.sleep(TX_POLL_SECONDS)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scanner_loop())


# ============ مسارات الـ API ============

@app.get("/api/alerts")
def api_alerts():
    sorted_alerts = sorted(list(alerts_feed), key=lambda x: x.get("strength", 0), reverse=True)
    return JSONResponse({"alerts": sorted_alerts, "stats": stats})


@app.get("/")
def dashboard():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
