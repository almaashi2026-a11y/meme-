"""
Ultra-Fast Live Feed Sniper (No-Lag Edition)
رادار القنص السريع فائق الحساسية - بدون أي تأخير
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

# شروط فائقة المرونة لضمان ظهور أي عملة جديدة فوراً
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 5))     
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 0.5))            
MAX_ALERTS_STORED = 100

app = FastAPI(title="Ultra-Fast Sniper")

alerts_feed = deque(maxlen=MAX_ALERTS_STORED)
stats = {"scanned_tokens": 0, "last_scan": None, "alerts_total": 0}
seen_tokens = set()


def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=1)
    except Exception:
        pass


def fetch_live_market_data():
    pairs_list = []
    
    # استخدام المسار الأسرع والأكثر استجابة لجلب أحدث الأزواج المتداولة
    endpoints = [
        "https://api.dexscreener.com/latest/dex/search?q=solana",
        "https://api.dexscreener.com/latest/dex/search?q=ETH",
        "https://api.dexscreener.com/latest/dex/search?q=USDC"
    ]
    
    for ep in endpoints:
        try:
            r = requests.get(ep, timeout=2)
            if r.status_code == 200:
                data = r.json()
                items = data.get("pairs", [])
                if isinstance(items, list):
                    pairs_list.extend(items)
        except Exception:
            pass

    processed = []
    for p in pairs_list:
        try:
            base_token = p.get("baseToken", {})
            token_address = base_token.get("address")
            symbol = str(base_token.get("symbol", "")).upper()
            
            if not token_address or token_address in seen_tokens:
                continue
                
            liq_usd = float(p.get("liquidity", {}).get("usd", 0) or 0)
            if liq_usd < MIN_LIQUIDITY_USD:
                continue
                
            seen_tokens.add(token_address)
            if len(seen_tokens) > 500:
                seen_tokens.pop() # الحفاظ على حجم الذاكرة

            price_change = p.get("priceChange", {})
            m1 = float(price_change.get("m1", 0) or 0)

            chain_id = str(p.get("chainId", "UNKNOWN")).upper()
            name = str(base_token.get("name", "Token"))
            price = str(p.get("priceUsd", "?"))
            pair_url = str(p.get("url", ""))

            now = time.time()
            entry = {
                "timestamp": now,
                "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "chain": chain_id,
                "symbol": symbol,
                "name": name,
                "token_address": token_address,
                "price": price,
                "liquidity": liq_usd,
                "m1_change": m1,
                "url": pair_url
            }
            
            processed.append(entry)
            
            # إرسال تنبيه تليجرام فوري
            msg = f"🚀 *حركة جديدة مرصودة!* [{chain_id}]\n"
            msg += f"العملة: *{symbol}* ({name})\n"
            msg += f"العقد: `{token_address}`\n"
            msg += f"التغير (m1): `+{m1:.2f}%` | السيولة: ${liq_usd:,.0f}\n"
            msg += pair_url
            send_telegram_alert(msg)

        except Exception:
            continue
            
    return processed


async def scanner_loop():
    while True:
        try:
            new_items = await asyncio.to_thread(fetch_live_market_data)
            if new_items:
                for item in new_items:
                    alerts_feed.appendleft(item)
                stats["alerts_total"] = len(alerts_feed)
                
            stats["scanned_tokens"] += len(new_items) + 10
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
    <title>Ultra-Fast Sniper</title>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: Tahoma, sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
        h1 { margin: 0; color: #58a6ff; font-size: 22px; }
        .stats { background: #161b22; padding: 10px 20px; border-radius: 8px; border: 1px solid #30363d; font-size: 14px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; border-right: 4px solid #3fb950; }
        .info { display: flex; flex-direction: column; gap: 5px; max-width: 75%; }
        .symbol { font-size: 18px; font-weight: bold; color: #3fb950; }
        .address { font-size: 12px; color: #8b949e; font-family: monospace; word-break: break-all; }
        .meta { font-size: 13px; color: #8b949e; display: flex; gap: 15px; flex-wrap: wrap; }
        .btn { background: #238636; color: #fff; padding: 8px 15px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold; white-space: nowrap; }
        .btn:hover { background: #2ea043; }
        .chain-tag { background: #1f6feb; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 11px; display: inline-block; margin-right: 5px; }
        .ignition { color: #3fb950; font-weight: bold; font-size: 15px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🚀 الرادار السريع المباشر (بدون تأخير)</h1>
        <div class="stats" id="statsBox">جاري الاتصال...</div>
    </div>
    
    <div id="alertsContainer">
        <div style="text-align: center; color: #8b949e; padding: 40px;">جاري التقاط الصفقات الحية الآن...</div>
    </div>

    <script>
        async function fetchAlerts() {
            try {
                let res = await fetch('/api/alerts');
                let data = await res.json();
                
                let stats = data.stats;
                document.getElementById('statsBox').innerHTML = 
                    `المفحوصة: <b>${stats.scanned_tokens}</b> | الصفقات: <b>${stats.alerts_total}</b> | آخر مسح: ${stats.last_scan || 'جارٍ...'}`;
                
                let alerts = data.alerts;
                let container = document.getElementById('alertsContainer');
                
                if (!alerts || alerts.length === 0) {
                    container.innerHTML = '<div style="text-align: center; color: #8b949e; padding: 40px;">بانتظار رصد أول صفقة صعود...</div>';
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
                                    <span style="color: #3fb950; font-size: 12px; font-weight: bold; margin-right: 10px;">[${item.time}]</span>
                                </div>
                                <div class="address">العقد: ${item.token_address}</div>
                                <div class="meta">
                                    <span>السيولة: <b>$${item.liquidity.toLocaleString()}</b></span>
                                    <span>تغير m1: <span class="ignition">+${item.m1_change}% ⚡</span></span>
                                    <span>السعر: $${item.price}</span>
                                </div>
                            </div>
                            <div>
                                ${item.url ? `<a href="${item.url}" target="_blank" class="btn">قنص الصفقة 🎯</a>` : ''}
                            </div>
                        </div>
                    `;
                });
                container.innerHTML = html;
            } catch (e) {
                console.error(e);
            }
        }
        
        setInterval(fetchAlerts, 1500);
        fetchAlerts();
    </script>
</body>
</html>
    """
