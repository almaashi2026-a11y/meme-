"""
Smart Money & Pump Radar (Unified Ultimate Edition)
الرادار المدمج الشامل - يعرض النتائج والداشبورد مباشرة بدون أي عوائق
"""

import asyncio
import time
import os
from collections import deque
from datetime import datetime, timezone

import requests
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

# ============ إعدادات الرادار الفوري ============

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 50))
MIN_VOLUME_USD = float(os.environ.get("MIN_VOLUME_USD", 10))
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 1.0))
MAX_ALERTS_STORED = 500
ALERT_COOLDOWN_SECONDS = 30

app = FastAPI(title="Smart Money & Pump Radar")

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


def fetch_all_active_pairs():
    pairs_list = []
    
    # 1. جلب الـ Profiles
    try:
        r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=2)
        if r.status_code == 200:
            profiles = r.json()
            if isinstance(profiles, list):
                addrs = [p.get("tokenAddress") for p in profiles[:100] if p.get("tokenAddress")]
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

    # 2. بحث شامل بالكلمات الساخنة
    queries = ["sol", "base", "eth", "bsc", "pump", "ai", "meme", "pepe", "doge", "cat", "sui", "arb"]
    for q in queries:
        try:
            rq = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={q}", timeout=1.5)
            if rq.status_code == 200:
                items = rq.json().get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items[:25])
        except Exception:
            pass

    seen, unique = set(), []
    for p in pairs_list:
        base_addr = p.get("baseToken", {}).get("address")
        if base_addr and base_addr not in seen:
            seen.add(base_addr)
            unique.append(p)
            
    return unique


def analyze_and_push(pair):
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

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair.get("baseToken", {}).get("symbol", "?")
    name = pair.get("baseToken", {}).get("name", "Token")
    price = pair.get("priceUsd", "?")
    pair_url = pair.get("url", "")
    
    price_change = pair.get("priceChange", {})
    h1_change = float(price_change.get("h1", 0) or 0)

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
        "url": pair_url,
        "strength": float(liq_usd + h1_vol)
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🎯 *رصد عملة جديدة* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"السيولة: ${liq_usd:,.0f} | 1h: {h1_change:+.1f}%\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)


async def scanner_loop():
    while True:
        pairs = await asyncio.to_thread(fetch_all_active_pairs)
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
    <title>Smart Money & Pump Radar - الاحترافي</title>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: Tahoma, sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; margin-bottom: 20px; }
        h1 { margin: 0; color: #58a6ff; font-size: 24px; }
        .stats { background: #161b22; padding: 10px 20px; border-radius: 8px; border: 1px solid #30363d; font-size: 14px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; }
        .info { display: flex; flex-direction: column; gap: 5px; }
        .symbol { font-size: 18px; font-weight: bold; color: #3fb950; }
        .address { font-size: 12px; color: #8b949e; font-family: monospace; }
        .meta { font-size: 13px; color: #d2a8ff; }
        .btn { background: #238636; color: #fff; padding: 8px 15px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold; }
        .btn:hover { background: #2ea043; }
        .chain-tag { background: #1f6feb; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 11px; display: inline-block; margin-right: 5px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 Smart Money & Pump Radar (الرادار الفوري)</h1>
        <div class="stats" id="statsBox">جاري تحديث الإحصائيات...</div>
    </div>
    
    <div id="alertsContainer">
        <div style="text-align: center; color: #8b949e; padding: 40px;">جاري رصد وجلب الفرص وتحميل العملات... يرجى الانتظار ثوانٍ معدودة.</div>
    </div>

    <script>
        async function fetchAlerts() {
            try {
                let res = await fetch('/api/alerts');
                let data = await res.json();
                
                let stats = data.stats;
                document.getElementById('statsBox').innerHTML = 
                    `العملات المفحوصة: <b>${stats.scanned_tokens}</b> | التنبيهات النشطة: <b>${stats.alerts_total}</b> | آخر مسح: ${stats.last_scan || 'جارٍ...'}`;
                
                let alerts = data.alerts;
                let container = document.getElementById('alertsContainer');
                
                if (alerts.length === 0) {
                    container.innerHTML = '<div style="text-align: center; color: #8b949e; padding: 40px;">الرادار يعمل ويبحث الآن... ستظهر العملات هنا فور مطابقتها للشروط.</div>';
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
                                </div>
                                <div class="address">العقد: ${item.token_address}</div>
                                <div class="meta">السيولة: $${item.liquidity.toLocaleString()} | الحجم (1س): $${item.volume.toLocaleString()} | التغير: ${item.h1_change >= 0 ? '+' : ''}${item.h1_change}% | السعر: $${item.price}</div>
                            </div>
                            <div>
                                ${item.url ? `<a href="${item.url}" target="_blank" class="btn">عرض على DexScreener</a>` : ''}
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
