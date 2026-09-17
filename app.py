"""
Smart Money & Pump Radar (Unique Gems Edition)
الرادار المدمج المصفى - منع التكرار واستبعاد العملات الكبرى والتركيز على الجواهر الحقيقية
"""

import asyncio
import time
import os
from collections import deque
from datetime import datetime, timezone

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# ============ إعدادات التنقية ومنع التكرار ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 500))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 200))
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 3.0))
MAX_ALERTS_STORED = 100
ALERT_COOLDOWN_SECONDS = 300  # منع تكرار نفس العملة لمدة 5 دقائق

# عناوين العملات الكبرى المستبعدة لمنع إغراق الشاشة بها
IGNORED_TOKENS = {
    "So11111111111111111111111111111111111111112",  # Native SOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC on Solana
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", # USDT on Solana
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH on Ethereum
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT on Ethereum
}

app = FastAPI(title="Smart Money & Pump Radar - Unique")

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


def fetch_unique_gems():
    pairs_list = []
    
    # استعلامات تركز على عملات الميم والمشاريع الجديدة النشطة
    queries = [
        "pump", "sol", "base", "ai", "meme", "pepe", "doge", 
        "cat", "wif", "bonk", "brett", "mog", "bome", "moon", "inu", "100x"
    ]
    
    for q in queries:
        try:
            rq = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={q}", timeout=1.5)
            if rq.status_code == 200:
                items = rq.json().get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items)
        except Exception:
            pass

    # تصفية وإزالة العملات الكبرى والتكرارات فوراً
    seen_addresses = set()
    unique = []
    
    for p in pairs_list:
        base_token = p.get("baseToken", {})
        token_address = base_token.get("address")
        
        if not token_address or token_address in IGNORED_TOKENS:
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
    
    if not token_address or token_address in IGNORED_TOKENS:
        return

    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    h1_vol = float(pair.get("volume", {}).get("h1", 0) or 0)
    if h1_vol < MIN_VOLUME_USD:
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = base_token.get("symbol", "?")
    name = base_token.get("name", "Token")
    price = pair.get("priceUsd", "?")
    pair_url = pair.get("url", "")
    
    price_change = pair.get("priceChange", {})
    h1_change = float(price_change.get("h1", 0) or 0)
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
        "strength": float(liq_usd + h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] = len(alerts_feed)

    msg = (
        f"💎 *فرصة جديدة فريدة* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"السيولة: ${liq_usd:,.0f} | 1س: {h1_change:+.1f}%\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(fetch_unique_gems)
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
    <title>Smart Money & Pump Radar - Unique Gems</title>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: Tahoma, sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
        h1 { margin: 0; color: #58a6ff; font-size: 22px; }
        .stats { background: #161b22; padding: 10px 20px; border-radius: 8px; border: 1px solid #30363d; font-size: 14px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
        .info { display: flex; flex-direction: column; gap: 5px; max-width: 75%; }
        .symbol { font-size: 18px; font-weight: bold; color: #3fb950; }
        .address { font-size: 12px; color: #8b949e; font-family: monospace; word-break: break-all; }
        .meta { font-size: 13px; color: #d2a8ff; display: flex; gap: 15px; flex-wrap: wrap; }
        .btn { background: #238636; color: #fff; padding: 8px 15px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold; white-space: nowrap; }
        .btn:hover { background: #2ea043; }
        .chain-tag { background: #1f6feb; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 11px; display: inline-block; margin-right: 5px; }
        .positive { color: #3fb950; font-weight: bold; }
        .negative { color: #f85149; font-weight: bold; }
    </style>
</head>
<body>
    <div class="header">
        <h1>💎 رادار الجواهر والعملات الفريدة (بدون تكرار)</h1>
        <div class="stats" id="statsBox">جاري تحديث الإحصائيات...</div>
    </div>
    
    <div id="alertsContainer">
        <div style="text-align: center; color: #8b949e; padding: 40px;">جاري تنقية وفلترة السوق من العملات الكبرى... تظهر الجواهر الفريدة الآن.</div>
    </div>

    <script>
        async function fetchAlerts() {
            try {
                let res = await fetch('/api/alerts');
                let data = await res.json();
                
                let stats = data.stats;
                document.getElementById('statsBox').innerHTML = 
                    `الفحوصات: <b>${stats.scanned_tokens}</b> | الجواهر الفريدة: <b>${stats.alerts_total}</b> | آخر مسح: ${stats.last_scan || 'جارٍ...'}`;
                
                let alerts = data.alerts;
                let container = document.getElementById('alertsContainer');
                
                if (alerts.length === 0) {
                    container.innerHTML = '<div style="text-align: center; color: #8b949e; padding: 40px;">الرادار يبحث وينقي النتائج... ستظهر العملات الفريدة هنا تباعاً.</div>';
                    return;
                }
                
                let html = '';
                alerts.forEach(item => {
                    let h1Class = item.h1_change >= 0 ? 'positive' : 'negative';
                    
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
                                    <span>تغير 1س: <span class="${h1Class}">${item.h1_change >= 0 ? '+' : ''}${item.h1_change}%</span></span>
                                    <span>السعر: $${item.price}</span>
                                </div>
                            </div>
                            <div>
                                ${item.url ? `<a href="${item.url}" target="_blank" class="btn">رابط السوق 🚀</a>` : ''}
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
