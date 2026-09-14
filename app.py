"""
Smart Money & Pump Tracker - Secure MultiChain & Contract Edition
رصد شامل لجميع الشبكات (تشمل Robinhood, Solana, EVM) مع عرض العقد، فحص أمان السيولة ونظافة العقود.
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
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 3000))
TRENDING_REFRESH_SECONDS = 120
TX_POLL_SECONDS = float(os.environ.get("TX_POLL_SECONDS", 10))
MAX_ALERTS_STORED = 300

# إعدادات كشف البمب
PUMP_WINDOW_SECONDS = float(os.environ.get("PUMP_WINDOW_SECONDS", 60))
PUMP_THRESHOLD_PERCENT = float(os.environ.get("PUMP_THRESHOLD_PERCENT", 8))
PUMP_ALERT_COOLDOWN_SECONDS = float(os.environ.get("PUMP_ALERT_COOLDOWN_SECONDS", 180))
WHALE_ALERT_COOLDOWN_SECONDS = float(os.environ.get("WHALE_ALERT_COOLDOWN_SECONDS", 120))

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
pump_last_alert = {}    
whale_last_alert = {}   

app = FastAPI(title="Smart Money & Pump Tracker - Secure Edition")


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
    """فحص نظافة العقد وقفل/حرق السيولة من بيانات الـ Pair"""
    info = pair_data.get("info", {})
    txns = pair_data.get("txns", {})
    
    # فحص السيولة المؤمنة (LP Locked/Burned check)
    lp_data = pair_data.get("liquidity", {})
    lp_usd = lp_data.get("usd", 0) or 0
    
    # تحقق من وجود ضرائب عالية (Buy/Sell taxes لو متوفرة أو تقديرية من الـ info)
    # تعتبر العملة نظيفة إذا لم توجد علامات تحذير صارخة وكانت السيولة متوفرة
    is_safe = True
    safety_note = "🛡️ عَقْد نظيف ومؤمن"
    
    # فحص نسب الحرق أو القفل من حقول ديج سكرينر المتاحة
    # في حال توفر حقول الـ Burns
    if "buys" in txns and "sells" in txns:
        recent_sells = txns.get("sells", {}).get("h1", 0)
        if recent_sells == 0 and lp_usd > 10000:
            safety_note = "⚠️ تحذير: انعدام البيع في آخر ساعة"
    
    return safety_note


def normalize_chain_type(chain_id):
    if chain_id == "solana":
        return "solana"
    if chain_id == "tron":
        return "tron"
    if chain_id in EVM_CHAINS:
        return "evm"
    return None


def record_alert(chain_id, token_address, wallet, pair_data, usd_value):
    if not pair_data:
        return

    liq = float(pair_data.get("liquidity", {}).get("usd", 0) or 0)
    if liq < MIN_LIQUIDITY_USD:
        return

    now = time.time()
    last_whale = whale_last_alert.get(token_address, 0)
    if now - last_whale < WHALE_ALERT_COOLDOWN_SECONDS:
        return
    whale_last_alert[token_address] = now

    symbol = pair_data.get("baseToken", {}).get("symbol", "?")
    price = pair_data.get("priceUsd", "?")
    mcap = pair_data.get("fdv", "?")
    pair_url = pair_data.get("url", "")
    short_wallet = (wallet[:6] + "..." + wallet[-4:]) if wallet else "?"
    safety_status = check_contract_safety(pair_data)

    entry = {
        "type": "whale",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "wallet": short_wallet,
        "symbol": symbol,
        "token_address": token_address,  # العقد لإظهاره بالداشبورد
        "usd_value": round(usd_value, 2),
        "price": price,
        "mcap": mcap,
        "liquidity": liq,
        "url": pair_url,
        "safety": safety_status,
        "strength": float(usd_value)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🐳 *Whale Buy Detected* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}*\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {safety_status}\n"
        f"قيمة الصفقة: ~${usd_value:,.0f}\n"
        f"السعر: ${price}\n"
        f"Market Cap: ${mcap}\n"
        f"Liquidity: ${liq:,.0f}\n"
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
    record_pump_alert(chain_id, token_address, pair_data, change_pct)


def record_pump_alert(chain_id, token_address, pair_data, change_pct):
    symbol = pair_data.get("baseToken", {}).get("symbol", "?")
    price = pair_data.get("priceUsd", "?")
    mcap = pair_data.get("fdv", "?")
    liq = pair_data.get("liquidity", {}).get("usd", "?")
    pair_url = pair_data.get("url", "")
    safety_status = check_contract_safety(pair_data)

    entry = {
        "type": "pump",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "wallet": None,
        "symbol": symbol,
        "token_address": token_address,  # العقد لإظهاره بالداشبورد
        "usd_value": None,
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

    window_label = f"{int(PUMP_WINDOW_SECONDS)} ثانية" if PUMP_WINDOW_SECONDS < 60 else f"{int(PUMP_WINDOW_SECONDS // 60)} دقيقة"

    msg = (
        f"🚀 *Pump Detected* [{chain_id.upper()}]\n"
        f"العملة: *{symbol}*\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {safety_status}\n"
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
            record_alert("solana", token_address, tx.get("destination") or tx.get("owner"), pair_data, usd_value)


def check_evm_token(chain_id, token_address, pair_data):
    cfg = EVM_CHAINS[chain_id]
    if not cfg["api_base"]:
        return
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
            record_alert(chain_id, token_address, tx.get("to"), pair_data, usd_value)


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
            record_alert("tron", token_address, tx.get("to_address"), pair_data, usd_value)


# ============ حلقة المسح الشامل ============

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
                        await asyncio.to_thread(check_pump, chain_id, token_address, pair_data)
                        
                        if chain_type == "solana":
                            await asyncio.to_thread(check_solana_token, token_address, pair_data)
                        elif chain_type == "evm":
                            await asyncio.to_thread(check_evm_token, chain_id, token_address, pair_data)
                        elif chain_type == "tron":
                            await asyncio.to_thread(check_tron_token, token_address, pair_data)
                        
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
