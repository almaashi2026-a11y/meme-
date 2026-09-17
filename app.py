"""
Smart Money & First-Tick Ignition Sniper (Real-time Chronological Edition)
رادار الشرارة الأولى - مرتب حسب الوقت والأحدث أولاً
"""

import asyncio
import time
import os
from collections import deque
from datetime import datetime, timezone

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# إعدادات الانفجار الفوري في الثواني الأولى
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 250))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 100))
MIN_M1_CHANGE = float(os.environ.get("MIN_M1_CHANGE", 2.0))   
MAX_M1_CHANGE = float(os.environ.get("MAX_M1_CHANGE", 90.0))  

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 1.5))     
MAX_ALERTS_STORED = 100
ALERT_COOLDOWN_SECONDS = 900

IGNORED_SYMBOLS = {"SOL", "ETH", "BTC", "USDT", "USDC", "BNB", "ARB", "SUI", "AVAX"}
IGNORED_TOKENS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "0xdac17f958d2ee523a2206206994597c13d831ec7",
}

app = FastAPI(title="Chronological Instant Sniper")

alerts_feed = deque(maxlen=MAX_ALERTS_STORED)
stats = {"scanned_tokens": 0, "last_scan": None, "alerts_total": 0}
last_alert_time = {}


def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=2)
    except Exception:
        pass


def fetch_safe_pairs():
    pairs_list = []
    
    try:
        r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=3)
        if r.status_code == 200:
            profiles = r.json()
            if isinstance(profiles, list):
                addrs = [p.get("tokenAddress") for p in profiles[:90] if p.get("tokenAddress")]
                if addrs:
                    rt = requests.get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(addrs[:30]), timeout=3)
                    if rt.status_code == 200:
                        items = rt.json().get("pairs", [])
                        if isinstance(items, list):
                            pairs_list.extend(items)
    except Exception:
        pass

    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=3)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addrs_b = [b.get("tokenAddress") for b in boosts[:70] if b.get("tokenAddress")]
                if addrs_b:
                    rb = requests.get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(addrs_b[:30]), timeout=3)
                    if rb.status_code == 200:
                        p_data = rb.json().get("pairs", [])
                        if isinstance(p_data, list):
                            pairs_list.extend(p_data)
    except Exception:
        pass

    seen_addresses = set()
    unique = []
    for p in pairs_list:
        try:
            base_token = p.get("baseToken", {})
            token_address = base_token.get("address")
            symbol = str(base_token.get("symbol", "")).upper()
            
            if not token_address or token_address in IGNORED_TOKENS:
                continue
            if symbol in IGNORED_SYMBOLS:
                continue
                
            if token_address not in seen_addresses:
                seen_addresses.add(token_address)
                unique.append(p)
        except Exception:
            continue
            
    return unique


def analyze_and_push(pair):
    try:
        if not pair:
            return

        chain_id = str(pair.get("chainId", "unknown")).upper()
        base_token = pair.get("baseToken", {})
        token_address = str(base_token.get("address", ""))
        symbol = str(base_token.get("symbol", "")).upper()
        
        if not token_address or token_address in IGNORED_TOKENS or symbol in IGNORED_SYMBOLS:
            return

        liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
        if liq_usd < MIN_LIQUIDITY_USD:
            return

        h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
        if h1_vol < MIN_VOLUME_USD:
            return

        price_change = pair.get("priceChange", {})
        m1_change = float(price_change.get("m1", 0) or 0)

        if not (MIN_M1_CHANGE <= m1_change <= MAX_M1_CHANGE):
            return

        now = time.time()
        if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
            return
        last_alert_time[token_address] = now

        name = str(base_token.get("name", "Token"))
        price = str(pair.get("priceUsd", "?"))
        pair_url = str(pair.get("url", ""))

        entry = {
            "timestamp": now,  # حقل زمني دقيق للترتيب
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "chain": chain_id,
            "symbol": symbol,
            "name": name,
            "token_address": token_address,
            "price": price,
            "liquidity": liq_usd,
            "volume": h1_vol,
            "m1_change": m1_change,
            "url": pair_url
        }
        
        # إدراج العنصر الجديد في البداية ليكون الأحدث دائماً في الصدارة
        alerts_feed.appendleft(entry)
        stats["alerts_total"] = len(alerts_feed)

        msg = "⚡ *الشرارة الأولى (اللحظة الأولى m1)!* [" + chain_id + "]\n"
        msg += "العملة: *" + symbol + "* (" + name + ")\n"
        msg += "العقد: `" + token_address + "`\n"
        msg += "🚀 تغير الدقيقة الأولى: *+" + f"{m1_change:.1f}" + "%* (انفجار فوري)\n"
        msg += "السيولة: $" + f"{liq_usd:,.0f}" + " \vert{} الحجم: $" + f"{h1_vol:,.0f}" + "\n"
        msg += pair_url
        
        send_telegram_alert(msg)
    except Exception:
        pass


async def scanner_loop():
    while True:
        try:
            pairs = await asyncio.to_thread(fetch_safe_pairs)
            if pairs:
                for p in pairs:
                    stats["scanned_tokens"] += 1
                    await asyncio.to_thread(analyze_and_push, p)
                
            stats["last_scan"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
        except Exception:
            pass
        await asyncio.sleep(POLL_SECONDS)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scanner_loop())


@app.get("/api/alerts")
def api_alerts():
    try:
        # ترتيب النتائج حصرياً حسب الوقت الأحدث أولاً (التاريخ التنازلي)
        sorted_alerts = sorted(list(alerts_feed), key=lambda x: x.get("timestamp", 0), reverse=True)
        return JSONResponse({"alerts": sorted_alerts, "stats": stats})
    except Exception:
        return JSONResponse({"alerts": [], "stats": stats})


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>Chronological Instant Sniper</title>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: Tahoma, sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
        h1 { margin: 0; color: #58a6ff; font-size: 22px; }
        .stats { background: #161b22; padding: 10px 20px; border-radius: 8px; border: 1px solid #30363d; font-size: 14px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; border-right: 4px solid #f85149; }
        .info { display: flex; flex-direction: column; gap: 5px; max-width: 75%; }
        .symbol { font-size: 18px; font-weight: bold; color: #ff7b72; }
        .address { font-size: 12px; color: #8b949e; font-family: monospace; word-break: break-all; }
        .meta { font-size: 13px; color: #8b949e; display: flex; gap: 15px; flex-wrap: wrap; }
        .btn { background: #da3633; color: #fff; padding: 8px 15px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold; white-space: nowrap; }
        .btn:hover { background: #f85149; }
        .chain-tag { background: #1f6feb; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 11px; display: inline-block; margin-right: 5px; }
        .ignition { color: #ff7b72; font-weight: bold; font-size: 15px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚡ رادار الشرارة الأولى (مرتب حسب الأحدث في الصدارة)</h1>
        <div class="stats" id="statsBox">جاري الاتصال بالسيرفر...</div>
    </div>
    
    <div id="alertsContainer">
        <div style="text-align: center; color: #8b949e; padding: 40px;">الرادار يعمل... بانتظار الانطلاقة الأولى.</div>
    </div>

    <script>
        async function fetchAlerts() {
            try {
                let res = await fetch('/api/alerts');
                let data = await res.json();
                
                let stats = data.stats;
                document.getElementById('statsBox').innerHTML = 
                    `المفحوصة: <b>${stats.scanned_tokens}</b> | الشرارات: <b>${stats.alerts_total}</b> | آخر مسح: ${stats.last_scan || 'جارٍ...'}`;
                
                let alerts = data.alerts;
                let container = document.getElementById('alertsContainer');
                
                if (!alerts || alerts.length === 0) {
                    container.innerHTML = '<div style="text-align: center; color: #8b949e; padding: 40px;">الرادار متصل يراقب أول ثانية من الانفجار... ستظهر العملات هنا فور تحركها.</div>';
                    return;
                }
                
                let html = '';
                alerts.forEach(item => {
                    html += `
                        <div class="card">
                            <div class="info">
                                <div>
                                    <span class="chain-tag">${item.chain}</span>
                                    <span class="symbol">${item.symbol}</span> 
                                    <span style="color: #8b949e; font-size: 13px;">(${item.name})</span>
                                    <span style="color: #3fb950; font-size: 12px; font-weight: bold; margin-right: 10px;">[وقت الرصد: ${item.time}]</span>
                                </div>
                                <div class="address">العقد: ${item.token_address}</div>
                                <div class="meta">
                                    <span>السيولة: <b>$${item.liquidity.toLocaleString()}</b></span>
                                    <span>الحجم: <b>$${item.volume.toLocaleString()}</b></span>
                                    <span>تغير الدقيقة 1: <span class="ignition">+${item.m1_change}% ⚡</span></span>
                                    <span>السعر: $${item.price}</span>
                                </div>
                            </div>
                            <div>
                                ${item.url ? `<a href="${item.url}" target="_blank" class="btn">قنص الشرارة 🎯</a>` : ''}
                            </div>
                        </div>
                    `;
                });
                container.innerHTML = html;
            } catch (e) {
                console.error(e);
            }
        }
        
        setInterval(fetchAlerts, 3000);
        fetchAlerts();
    </script>
</body>
</html>
    """
