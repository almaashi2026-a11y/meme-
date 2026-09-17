"""
Smart Money & Pump Radar (Absolute Momentum Sniper Edition)
رادار القناص اللحظي للزخم - صواريخ حقيقية وفلترة صارمة للنسب المرتفعة فقط
"""

import asyncio
import time
import os
from collections import deque
from datetime import datetime, timezone

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# ============ إعدادات القناص العنيف ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# شروط صارمة جداً: لا تقبل إلا العملات التي تتحرك بعنف وتغير حقيقي
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 500))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 500))
MIN_H1_CHANGE = float(os.environ.get("MIN_H1_CHANGE", 25.0))  # اشتراط صعود +25% كحد أدنى حقيقي

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 3.0))
MAX_ALERTS_STORED = 100
ALERT_COOLDOWN_SECONDS = 600

# قائمة حظر شاملة لأي عملة كبرى أو أساسية قد تتسرب
IGNORED_SYMBOLS = {"SOL", "ETH", "BTC", "USDT", "USDC", "BNB", "ARB", "SUI", "AVAX"}
IGNORED_TOKENS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "0xdac17f958d2ee523a2206206994597c13d831ec7",
}

app = FastAPI(title="Absolute Momentum Sniper")

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
        }, timeout=2)
    except Exception:
        pass


def fetch_pure_momentum_pairs():
    pairs_list = []
    
    # 1. سحب أحدث الـ Token Profiles (أحدث المشاريع المُضافَة)
    try:
        r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=2)
        if r.status_code == 200:
            profiles = r.json()
            if isinstance(profiles, list):
                addrs = [p.get("tokenAddress") for p in profiles[:150] if p.get("tokenAddress")]
                if addrs:
                    for i in range(0, len(addrs), 30):
                        chunk = addrs[i:i+30]
                        rt = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(chunk)}", timeout=2)
                        if rt.status_code == 200:
                            items = rt.json().get("pairs", [])
                            if isinstance(items, list):
                                pairs_list.extend(items)
    except Exception:
        pass

    # 2. سحب أحدث الـ Token Boosts (العملات المدعومة والنشطة مضاربياً)
    try:
        r2 = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=2)
        if r2.status_code == 200:
            boosts = r2.json()
            if isinstance(boosts, list):
                addrs_b = [b.get("tokenAddress") for b in boosts[:100] if b.get("tokenAddress")]
                if addrs_b:
                    for i in range(0, len(addrs_b), 30):
                        chunk_b = addrs_b[i:i+30]
                        rb = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(chunk_b)}", timeout=2)
                        if rb.status_code == 200:
                            p_data = rb.json().get("pairs", [])
                            if isinstance(p_data, list):
                                pairs_list.extend(p_data)
    except Exception:
        pass

    # تصفية ومنع التكرار واستبعاد العملات الكبرى تماماً
    seen_addresses = set()
    unique = []
    
    for p in pairs_list:
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
            
    return unique


def analyze_and_push(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown").upper()
    base_token = pair.get("baseToken", {})
    token_address = base_token.get("address", "")
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
    h1_change = float(price_change.get("h1", 0) or 0)

    # 🚀 الشرط الحاسم: استبعاد أي عملة صعودها أقل من الحد الأدنى للصاروخ (+25%)
    if h1_change < MIN_H1_CHANGE:
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    name = base_token.get("name", "Token")
    price = pair.get("priceUsd", "?")
    pair_url = pair.get("url", "")
    h24_change = float(price_change.get("h24", 0) or 0)

    entry = {
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "chain": chain_id,
        "symbol": symbol,
        "name": name,
        "token_address": token_address,
        "price": str(price),
        "liquidity": liq_usd,
        "volume": h1_vol,
        "h1_change": h1_change,
        "h24_change": h24_change,
        "url": pair_url,
        "strength": float(h1_change * h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] = len(alerts_feed)

    msg = (
        f"🚀 *صاروخ سوق مرصود!* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"🔥 صعود الساعة (1س): *+{h1_change:.1f}%*\n"
        f"السيولة: ${liq_usd:,.0f} \vert{} الحجم: ${h1_vol:,.0f}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(fetch_pure_momentum_pairs)
        if pairs:
            for p in pairs:
                stats["scanned_tokens"] += 1
                await asyncio.to_thread(analyze_and_push, p)
            
        stats["last_scan"] = datetime.now(timezone.utc).strftime("%H:%M:%S")
        await asyncio.sleep(POLL_SECONDS)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scanner_loop())


@app.get("/api/alerts")
def api_alerts():
    sorted_alerts = sorted(list(alerts_feed), key=lambda x: x.get("strength", 0), reverse=True)
    return JSONResponse({"alerts": sorted_alerts, "stats": stats})


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>Absolute Momentum Sniper</title>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: Tahoma, sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
        h1 { margin: 0; color: #58a6ff; font-size: 22px; }
        .stats { background: #161b22; padding: 10px 20px; border-radius: 8px; border: 1px solid #30363d; font-size: 14px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; border-right: 4px solid #3fb950; }
        .info { display: flex; flex-direction: column; gap: 5px; max-width: 75%; }
        .symbol { font-size: 18px; font-weight: bold; color: #3fb950; }
        .address { font-size: 12px; color: #8b949e; font-family: monospace; word-break: break-all; }
        .meta { font-size: 13px; color: #d2a8ff; display: flex; gap: 15px; flex-wrap: wrap; }
        .btn { background: #238636; color: #fff; padding: 8px 15px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold; white-space: nowrap; }
        .btn:hover { background: #2ea043; }
        .chain-tag { background: #1f6feb; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 11px; display: inline-block; margin-right: 5px; }
        .explosive { color: #3fb950; font-weight: bold; font-size: 15px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🎯 رادار صواريخ الزخم اللحظي (مستبعد العملات الباردة)</h1>
        <div class="stats" id="statsBox">جاري فحص السوق...</div>
    </div>
    
    <div id="alertsContainer">
        <div style="text-align: center; color: #8b949e; padding: 40px;">الرادار الآن يراقب حصرياً أحدث المشاريع الصاعدة بقوة (+25% فأكثر)... انتظر ظهور الصواريخ المشتعلة.</div>
    </div>

    <script>
        async function fetchAlerts() {
            try {
                let res = await fetch('/api/alerts');
                let data = await res.json();
                
                let stats = data.stats;
                document.getElementById('statsBox').innerHTML = 
                    `المفحوصة: <b>${stats.scanned_tokens}</b> | الصواريخ المرصودة: <b>${stats.alerts_total}</b> | آخر مسح: ${stats.last_scan || 'جارٍ...'}`;
                
                let alerts = data.alerts;
                let container = document.getElementById('alertsContainer');
                
                if (alerts.length === 0) {
                    container.innerHTML = '<div style="text-align: center; color: #8b949e; padding: 40px;">الرادار شغال وبقوة... بانتظار تطابق الشروط الصاروخية وظهور أول عملة منفجرة.</div>';
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
                                    <span style="color: #8b949e; font-size: 11px; margin-right: 10px;">[وقت الرصد: ${item.time}]</span>
                                </div>
                                <div class="address">العقد: ${item.token_address}</div>
                                <div class="meta">
                                    <span>السيولة: <b>$${item.liquidity.toLocaleString()}</b></span>
                                    <span>الحجم (1س): <b>$${item.volume.toLocaleString()}</b></span>
                                    <span>تغير 1س: <span class="explosive">+${item.h1_change}% 🚀</span></span>
                                    <span>السعر: $${item.price}</span>
                                </div>
                            </div>
                            <div>
                                ${item.url ? `<a href="${item.url}" target="_blank" class="btn">رابط الصاروخ 🎯</a>` : ''}
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
