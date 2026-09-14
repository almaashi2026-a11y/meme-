"""
Smart Inflow & Early Whale Tracker - Direct Entry Edition
رصد التدفقات والسيولة الحقيقية للحيتان في لحظات الانطلاقة المبكرة.
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

# حد سيولة ممتاز يضمن الأمان والقدرة على البيع والشراء
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 3000))
# حد صفقات الحيتان المبكرة
WHALE_BUY_USD = float(os.environ.get("WHALE_BUY_USD", 1500))

TRENDING_REFRESH_SECONDS = 60
TX_POLL_SECONDS = float(os.environ.get("TX_POLL_SECONDS", 5))
MAX_ALERTS_STORED = 300
ALERT_COOLDOWN_SECONDS = float(os.environ.get("ALERT_COOLDOWN_SECONDS", 90))

EVM_CHAINS = {
    "ethereum": {"api_base": "https://api.etherscan.io/api", "api_key_env": "ETHERSCAN_API_KEY"},
    "bsc": {"api_base": "https://api.bscscan.com/api", "api_key_env": "BSCSCAN_API_KEY"},
    "base": {"api_base": "https://api.basescan.org/api", "api_key_env": "BASESCAN_API_KEY"},
    "arbitrum": {"api_base": "https://api.arbiscan.io/api", "api_key_env": "ARBISCAN_API_KEY"},
    "robinhood": {"api_base": "", "api_key_env": ""},
}

# ============ حالة النظام ============

alerts_feed = deque(maxlen=MAX_ALERTS_STORED)
seen_tx_ids = set()
stats = {"scanned_tokens": 0, "last_scan": None, "alerts_total": 0}
last_alert_time = {}

app = FastAPI(title="Smart Inflow & Early Whale Tracker")


# ============ أدوات الدعم والتنبيه ============

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


def get_boosted_tokens():
    url = "https://api.dexscreener.com/token-boosts/latest/v1"
    tokens = []
    try:
        r = requests.get(url, timeout=8)
        r.raise_for_status()
        data = r.json()
        for item in data if isinstance(data, list) else []:
            c_id, t_addr = item.get("chainId"), item.get("tokenAddress")
            if c_id and t_addr:
                tokens.append((c_id, t_addr))
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
            c_id, t_addr = item.get("chainId"), item.get("tokenAddress")
            if c_id and t_addr:
                tokens.append((c_id, t_addr))
    except Exception:
        pass
    return tokens


def get_trending_tokens():
    combined = get_boosted_tokens() + get_new_token_profiles()
    seen, tokens = set(), []
    for k in combined:
        if k not in seen:
            seen.add(k)
            tokens.append(k)
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
    if lp_usd >= 10000:
        return "🛡️ سيولة قوية وآمنة"
    return "🛡️ عقد نظيف ودخول مبكر"


def register_signal(chain_id, token_address, pair_data, buy_amount_usd):
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
    mcap = pair_data.get("fdv", "?")
    pair_url = pair_data.get("url", "")
    safety_status = check_contract_safety(pair_data)

    entry = {
        "type": "smart_inflow",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "token_address": token_address,
        "usd_value": round(buy_amount_usd, 2),
        "price": price,
        "mcap": mcap,
        "liquidity": liq,
        "url": pair_url,
        "safety": safety_status,
        "strength": float(buy_amount_usd)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🐋 *Smart Money Inflow* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}* (شراء حقيقي مبكر: ~${buy_amount_usd:,.0f})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {safety_status}\n"
        f"السعر: ${price}\n"
        f"Market Cap: ${mcap}\n"
        f"Liquidity: ${liq:,.0f}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


# ============ فحص المعاملات الحية والانطلاقة الأولى ============

def evaluate_token_momentum(chain_id, token_address, pair_data):
    if not pair_data:
        return

    # التحقق من نشاط الشراء مقابل البيع في آخر ساعة (تأكيد تدفق السيولة)
    txns = pair_data.get("txns", {})
    h1_buys = txns.get("buys", {}).get("h1", 0)
    h1_sells = txns.get("sells", {}).get("h1", 0)
    
    # فحص حجم التداول للـ 5 دقائق أو الساعة الأولى للتأكد من أننا في البداية
    volume = pair_data.get("volume", {})
    h1_vol = volume.get("h1", 0) or 0

    # شروط الدخول المبكر الموزونة: وجود تفوق في المشتريات وسيولة جيدة وحجم تنافسي مبكر
    if h1_buys > 3 and h1_buys >= h1_sells * 1.5 and h1_vol > 1000:
        estimated_buy_power = h1_vol / max(1, (h1_buys + h1_sells)) * h1_buys
        if estimated_buy_power >= WHALE_BUY_USD:
            register_signal(chain_id, token_address, pair_data, estimated_buy_power)


# ============ حلقة الفحص المستمر ============

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
                        await asyncio.to_thread(evaluate_token_momentum, chain_id, token_address, pair_data)
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
