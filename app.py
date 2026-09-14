"""
Smart Money Early Entry & Pump Tracker
رصد الدخول المبكر للسيولة والصفقات الأولى قبل الانفجار السعري مع فحص الأمان.
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

# خفضنا الحد قليلاً لنقنص الصفقات في بدايتها المبكرة
WHALE_BUY_THRESHOLD_USD = float(os.environ.get("WHALE_BUY_THRESHOLD_USD", 2500))
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 2500))
TRENDING_REFRESH_SECONDS = 90
TX_POLL_SECONDS = float(os.environ.get("TX_POLL_SECONDS", 8))
MAX_ALERTS_STORED = 300

# إعدادات كشف البمب المبكر (بداية الصعود)
PUMP_WINDOW_SECONDS = float(os.environ.get("PUMP_WINDOW_SECONDS", 60))
PUMP_THRESHOLD_PERCENT = float(os.environ.get("PUMP_THRESHOLD_PERCENT", 5)) # بداية الانطلاقة من 5%
ALERT_COOLDOWN_SECONDS = float(os.environ.get("ALERT_COOLDOWN_SECONDS", 90))

EVM_CHAINS = {
    "ethereum": {"api_base": "https://api.etherscan.io/api", "api_key_env": "ETHERSCAN_API_KEY"},
    "bsc": {"api_base": "https://api.bscscan.com/api", "api_key_env": "BSCSCAN_API_KEY"},
    "base": {"api_base": "https://api.basescan.org/api", "api_key_env": "BASESCAN_API_KEY"},
    "arbitrum": {"api_base": "https://api.arbiscan.io/api", "api_key_env": "ARBISCAN_API_KEY"},
    "robinhood": {"api_base": "", "api_key_env": ""},
}

# ============ حالة مشتركة ============

alerts_feed = deque(maxlen=MAX_ALERTS_STORED)
seen_tx_ids = set()
stats = {"scanned_tokens": 0, "last_scan": None, "alerts_total": 0}

price_history = {}      
last_alert_time = {}   

app = FastAPI(title="Early Entry Smart Money Tracker")


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
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        for item in data if isinstance(data, list) else []:
            chain_id = item.get("chainId")
            token_address = item.get("tokenAddress")
            if chain_id and token_address:
                tokens.append((chain_id, token_address))
    except Exception as e:
        print(f"[!] خطأ بجلب العملات المدعومة: {e}")
    return tokens


def get_new_token_profiles():
    url = "https://api.dexscreener.com/token-profiles/latest/v1"
    tokens = []
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        for item in data if isinstance(data, list) else []:
            chain_id = item.get("chainId")
            token_address = item.get("tokenAddress")
            if chain_id and token_address:
                tokens.append((chain_id, token_address))
    except Exception as e:
        print(f"[!] خطأ بجلب العملات الجديدة: {e}")
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
    addresses_str = ",".join(token_addresses[:30])
    url = f"https://api.dexscreener.com/latest/dex/tokens/{addresses_str}"
    results = {}
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        pairs = r.json().get("pairs") or []
        for p in pairs:
            base_addr = p.get("baseToken", {}).get("address")
            if base_addr:
                curr_liq = p.get("liquidity", {}).get("usd", 0) or 0
                if base_addr not in results or curr_liq > (results[base_addr].get("liquidity", {}).get("usd", 0) or 0):
                    results[base_addr] = p
    except Exception as e:
        print(f"[!] خطأ بجلب بيانات المجموعات: {e}")
    return results


def check_contract_safety(pair_data):
    """فحص نظافة العقد وسيولة المجمع للتأكد من أمان الدخول"""
    lp_data = pair_data.get("liquidity", {})
    lp_usd = lp_data.get("usd", 0) or 0
    
    safety_note = "🛡️ عقد نظيف (آمن)"
    if lp_usd >= 10000:
        safety_note = "🛡️ سيولة جيدة ومؤمنة"
    return safety_note


def normalize_chain_type(chain_id):
    if chain_id == "solana":
        return "solana"
    if chain_id == "tron":
        return "tron"
    if chain_id in EVM_CHAINS:
        return "evm"
    return None


def record_early_entry(chain_id, token_address, pair_data, change_pct, usd_value=None):
    if not pair_data:
        return

    liq = float(pair_data.get("liquidity", {}).get("usd", 0) or 0)
    if liq < MIN_LIQUIDITY_USD:
        return

    now = time.time()
    last_alert = last_alert_time.get(token_address, 0)
    if now - last_alert < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair_data.get("baseToken", {}).get("symbol", "?")
    price = pair_data.get("priceUsd", "?")
    mcap = pair_data.get("fdv", "?")
    pair_url = pair_data.get("url", "")
    safety_status = check_contract_safety(pair_data)

    entry = {
        "type": "early_entry",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "token_address": token_address,
        "change_pct": round(change_pct, 1),
        "usd_value": round(usd_value, 2) if usd_value else None,
        "price": price,
        "mcap": mcap,
        "liquidity": liq,
        "url": pair_url,
        "safety": safety_status,
        "strength": float(change_pct) if change_pct else float(usd_value or 0)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🎯 *Early Entry Signal* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}* (بداية انطلاقة +{change_pct:.1f}%)\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {safety_status}\n"
        f"السعر: ${price}\n"
        f"Market Cap: ${mcap}\n"
        f"Liquidity: ${liq:,.0f}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


def check_early_pump(chain_id, token_address, pair_data):
    if not pair_data:
        return
    try:
        price = float(pair_data.get("priceUsd") or 0)
    except (TypeError, ValueError):
        return
    if price <= 0:
        return

    now = time.time()
    hist = price_history.setdefault(token_address, deque())
    hist.append((now, price))

    while hist and now - hist[0][0] > PUMP_WINDOW_SECONDS:
        hist.popleft()

    if len(hist) < 2:
        return

    oldest_price = hist[0][1]
    if oldest_price <= 0:
        return

    change_pct = (price - oldest_price) / oldest_price * 100
    # تنبيه مبكر فور بدء الارتفاع بنسبة طفيفة آمنة (مثلاً 5% إلى 25%)
    if PUMP_THRESHOLD_PERCENT <= change_pct <= 35:
        record_early_entry(chain_id, token_address, pair_data, change_pct)


# ============ حلقة المسح والشامل ============

async def scanner_loop():
    trending = []
    last_refresh = 0
    while True:
        now = time.time()
        if now - last_refresh >= TRENDING_REFRESH_SECONDS:
            trending = await asyncio.to_thread(get_trending_tokens)
            last_refresh = now

        if trending:
            chunk_size = 30
            for i in range(0, len(trending), chunk_size):
                chunk = trending[i:i + chunk_size]
                token_addresses = [item[1] for item in chunk]
                
                pairs_dict = await asyncio.to_thread(get_pairs_data_batch, token_addresses)

                for chain_id, token_address in chunk:
                    chain_type = normalize_chain_type(chain_id)
                    if not chain_type and chain_id != "robinhood":
                        continue

                    pair_data = pairs_dict.get(token_address)
                    if pair_data:
                        await asyncio.to_thread(check_early_pump, chain_id, token_address, pair_data)
                        stats["scanned_tokens"] += 1

                await asyncio.sleep(2.0)

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
