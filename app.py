"""
Smart Money & Pump Tracker - Dashboard Edition
تطبيق متكامل: مسح تلقائي للخلفية للعملات + رصد البمب لحظياً + صفقات الحيتان + داشبورد ويب + تنبيهات تليجرام.

المتطلبات:
    pip install fastapi uvicorn requests

التشغيل محلياً:
    uvicorn app:app --host 0.0.0.0 --port 8000
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

WHALE_BUY_THRESHOLD_USD = float(os.environ.get("WHALE_BUY_THRESHOLD_USD", 5000))
TRENDING_REFRESH_SECONDS = 120
TX_POLL_SECONDS = float(os.environ.get("TX_POLL_SECONDS", 5))  # فحص سريع كل 5 ثوانٍ
MAX_ALERTS_STORED = 300

# إعدادات كشف البمب (ارتفاع سعر مفاجئ)
PUMP_WINDOW_SECONDS = float(os.environ.get("PUMP_WINDOW_SECONDS", 60))        # نافذة المراقبة (دقيقة)
PUMP_THRESHOLD_PERCENT = float(os.environ.get("PUMP_THRESHOLD_PERCENT", 8))   # نسبة الصعود لاعتبارها بمب
PUMP_ALERT_COOLDOWN_SECONDS = float(os.environ.get("PUMP_ALERT_COOLDOWN_SECONDS", 180)) # منع تكرار التنبيه

EVM_CHAINS = {
    "ethereum": {"api_base": "https://api.etherscan.io/api", "api_key_env": "ETHERSCAN_API_KEY"},
    "bsc": {"api_base": "https://api.bscscan.com/api", "api_key_env": "BSCSCAN_API_KEY"},
    "base": {"api_base": "https://api.basescan.org/api", "api_key_env": "BASESCAN_API_KEY"},
    "arbitrum": {"api_base": "https://api.arbiscan.io/api", "api_key_env": "ARBISCAN_API_KEY"},
}

# ============ حالة مشتركة (بالذاكرة) ============

alerts_feed = deque(maxlen=MAX_ALERTS_STORED)
seen_tx_ids = set()
stats = {"scanned_tokens": 0, "last_scan": None, "alerts_total": 0}

price_history = {}   # token_address -> deque[(timestamp, price)]
pump_last_alert = {}  # token_address -> آخر وقت انبعث فيه تنبيه بمب

app = FastAPI(title="Smart Money & Pump Tracker")


# ============ أدوات مساعدة ============

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


def get_pair_data(chain_id, token_address):
    url = f"https://api.dexscreener.com/latest/dex/tokens/{token_address}"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        pairs = r.json().get("pairs") or []
        matching = [p for p in pairs if p.get("chainId") == chain_id]
        if matching:
            return max(matching, key=lambda p: p.get("liquidity", {}).get("usd", 0) or 0)
    except Exception as e:
        print(f"[!] خطأ بجلب بيانات الزوج {token_address}: {e}")
    return None


def normalize_chain_type(chain_id):
    if chain_id == "solana":
        return "solana"
    if chain_id == "tron":
        return "tron"
    if chain_id in EVM_CHAINS:
        return "evm"
    return None


def record_alert(chain_id, wallet, pair_data, usd_value):
    symbol = pair_data.get("baseToken", {}).get("symbol", "?") if pair_data else "?"
    price = pair_data.get("priceUsd", "?") if pair_data else "?"
    mcap = pair_data.get("fdv", "?") if pair_data else "?"
    liq = pair_data.get("liquidity", {}).get("usd", "?") if pair_data else "?"
    pair_url = pair_data.get("url", "") if pair_data else ""
    short_wallet = (wallet[:6] + "..." + wallet[-4:]) if wallet else "?"

    entry = {
        "type": "whale",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "wallet": short_wallet,
        "symbol": symbol,
        "usd_value": round(usd_value, 2),
        "price": price,
        "mcap": mcap,
        "liquidity": liq,
        "url": pair_url,
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🐳 *Whale Buy Detected* [{chain_id.upper()}]\n"
        f"المحفظة: `{short_wallet}`\n"
        f"العملة: *{symbol}*\n"
        f"قيمة الصفقة: ~${usd_value:,.0f}\n"
        f"السعر: ${price}\n"
        f"Market Cap: ${mcap}\n"
        f"Liquidity: ${liq}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


def check_pump(chain_id, token_address, pair_data):
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
    if change_pct < PUMP_THRESHOLD_PERCENT:
        return

    last_alert = pump_last_alert.get(token_address, 0)
    if now - last_alert < PUMP_ALERT_COOLDOWN_SECONDS:
        return

    pump_last_alert[token_address] = now
    record_pump_alert(chain_id, pair_data, change_pct)


def record_pump_alert(chain_id, pair_data, change_pct):
    symbol = pair_data.get("baseToken", {}).get("symbol", "?")
    price = pair_data.get("priceUsd", "?")
    mcap = pair_data.get("fdv", "?")
    liq = pair_data.get("liquidity", {}).get("usd", "?")
    pair_url = pair_data.get("url", "")

    entry = {
        "type": "pump",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "wallet": None,
        "symbol": symbol,
        "usd_value": None,
        "change_pct": round(change_pct, 1),
        "price": price,
        "mcap": mcap,
        "liquidity": liq,
        "url": pair_url,
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    window_label = f"{int(PUMP_WINDOW_SECONDS)} ثانية" if PUMP_WINDOW_SECONDS < 60 else f"{int(PUMP_WINDOW_SECONDS // 60)} دقيقة"

    msg = (
        f"🚀 *Pump Detected* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}*\n"
        f"ارتفاع: +{change_pct:.1f}% خلال {window_label}\n"
        f"السعر الحالي: ${price}\n"
        f"Market Cap: ${mcap}\n"
        f"Liquidity: ${liq}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


# ============ فحص التحويلات ============

def check_solana_token(token_address, pair_data):
    url = "https://public-api.solscan.io/token/transfer"
    try:
        r = requests.get(url, params={"tokenAddress": token_address, "limit": 10}, timeout=10)
        r.raise_for_status()
        txs = r.json().get("data", [])
    except Exception:
        return

    price = float(pair_data.get("priceUsd") or 0) if pair_data else 0
    for tx in txs:
        tx_id = tx.get("signature") or tx.get("txHash")
        if not tx_id or tx_id in seen_tx_ids:
            continue
        seen_tx_ids.add(tx_id)
        decimals = tx.get("decimals", 0)
        amount = float(tx.get("amount", 0)) / (10 ** decimals) if decimals else 0
        usd_value = price * amount
        if usd_value >= WHALE_BUY_THRESHOLD_USD:
            record_alert("solana", tx.get("destination") or tx.get("owner"), pair_data, usd_value)


def check_evm_token(chain_id, token_address, pair_data):
    cfg = EVM_CHAINS[chain_id]
    api_key = os.environ.get(cfg["api_key_env"], "")
    params = {
        "module": "account", "action": "tokentx", "contractaddress": token_address,
        "sort": "desc", "page": 1, "offset": 15, "apikey": api_key,
    }
    try:
        r = requests.get(cfg["api_base"], params=params, timeout=10)
        r.raise_for_status()
        result = r.json().get("result", [])
        if not isinstance(result, list):
            return
    except Exception:
        return

    price = float(pair_data.get("priceUsd") or 0) if pair_data else 0
    for tx in result:
        tx_id = tx.get("hash")
        if not tx_id or tx_id in seen_tx_ids:
            continue
        seen_tx_ids.add(tx_id)
        decimals = int(tx.get("tokenDecimal", 18) or 18)
        amount = int(tx.get("value", 0) or 0) / (10 ** decimals)
        usd_value = price * amount
        if usd_value >= WHALE_BUY_THRESHOLD_USD:
            record_alert(chain_id, tx.get("to"), pair_data, usd_value)


def check_tron_token(token_address, pair_data):
    url = "https://apilist.tronscanapi.com/api/token_trc20/transfers"
    try:
        r = requests.get(url, params={"contract_address": token_address, "limit": 10, "start": 0}, timeout=10)
        r.raise_for_status()
        txs = r.json().get("token_transfers", [])
    except Exception:
        return

    price = float(pair_data.get("priceUsd") or 0) if pair_data else 0
    for tx in txs:
        tx_id = tx.get("transaction_id")
        if not tx_id or tx_id in seen_tx_ids:
            continue
        seen_tx_ids.add(tx_id)
        decimals = int(tx.get("decimals", 6) or 6)
        amount = int(tx.get("quant", 0) or 0) / (10 ** decimals)
        usd_value = price * amount
        if usd_value >= WHALE_BUY_THRESHOLD_USD:
            record_alert("tron", tx.get("to_address"), pair_data, usd_value)


# ============ حلقة المسح الخلفية ============

async def scanner_loop():
    trending = []
    last_refresh = 0
    while True:
        now = time.time()
        if now - last_refresh >= TRENDING_REFRESH_SECONDS:
            trending = await asyncio.to_thread(get_trending_tokens)
            last_refresh = now

        for chain_id, token_address in trending:
            chain_type = normalize_chain_type(chain_id)
            if not chain_type:
                continue
            pair_data = await asyncio.to_thread(get_pair_data, chain_id, token_address)
            await asyncio.to_thread(check_pump, chain_id, token_address, pair_data)
            if chain_type == "solana":
                await asyncio.to_thread(check_solana_token, token_address, pair_data)
            elif chain_type == "evm":
                await asyncio.to_thread(check_evm_token, chain_id, token_address, pair_data)
            elif chain_type == "tron":
                await asyncio.to_thread(check_tron_token, token_address, pair_data)
            stats["scanned_tokens"] += 1
            
            # فاصل زمني لتجنب الضغط على الـ API ومنع خطأ 429
            await asyncio.sleep(0.4)

        stats["last_scan"] = datetime.now(timezone.utc).isoformat()
        await asyncio.sleep(TX_POLL_SECONDS)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scanner_loop())


# ============ مسارات الـ API والداشبورد ============

@app.get("/api/alerts")
def api_alerts():
    return JSONResponse({"alerts": list(alerts_feed), "stats": stats})


@app.get("/")
def dashboard():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")
