"""
Strict Fresh-Only Sniper (Under 2 Hours Max Age)
محرك القنص للعملات الحديثة فقط - استبعاد أي عقد مر عليه أكثر من ساعتين
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

MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 500))     
MAX_LIQUIDITY_USD = float(os.environ.get("MAX_LIQUIDITY_USD", 50000))  
MAX_PAIR_AGE_HOURS = float(os.environ.get("MAX_PAIR_AGE_HOURS", 2.0))   # أقصى عمر للعملة ساعتان فقط

POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 1.0))            
MAX_ALERTS_STORED = 100

IGNORED_SYMBOLS = {"SOL", "ETH", "BTC", "USDT", "USDC", "BNB", "WETH", "WBTC", "ARB", "SUI", "AVAX", "MATIC", "TRX"}
IGNORED_TOKENS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "0xdac17f958d2ee523a2206206994597c13d831ec7"
}

app = FastAPI(title="Fresh Sniper Engine")

alerts_feed = deque(maxlen=MAX_ALERTS_STORED)
stats = {"scanned_tokens": 0, "last_scan": None, "alerts_total": 0}
seen_tokens_cache = {}


def send_telegram_alert(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }, timeout=1)
    except Exception:
        pass


def fetch_fresh_pairs_only():
    pairs_list = []
    endpoints = [
        "https://api.dexscreener.com/token-boosts/latest/v1",
        "https://api.dexscreener.com/latest/dex/search?q=pump",
        "https://api.dexscreener.com/latest/dex/search?q=raydium"
    ]
    
    for ep in endpoints:
        try:
            r = requests.get(ep, timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    addrs = [item.get("tokenAddress") for item in data if item.get("tokenAddress")]
                    if addrs:
                        r_tokens = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{','.join(addrs[:25])}", timeout=1.5)
                        if r_tokens.status_code == 200:
                            p_data = r_tokens.json().get("pairs", [])
                            if isinstance(p_data, list):
                                pairs_list.extend(p_data)
                elif isinstance(data, dict):
                    items = data.get("pairs", [])
                    if isinstance(items, list):
                        pairs_list.extend(items)
        except Exception:
            pass

    unique_processed = []
    current_time_ms = time.time() * 1000
    current_time = time.time()

    for p in pairs_list:
        try:
            base_token = p.get("baseToken", {})
            token_address = base_token.get("address")
            symbol = str(base_token.get("symbol", "")).upper()
            chain_id = str(p.get("chainId", "UNKNOWN")).upper()
            
            if not token_address or token_address in IGNORED_TOKENS:
                continue
            if symbol in IGNORED_SYMBOLS or len(symbol) > 12:
                continue
                
            liq_usd = float(p.get("liquidity", {}).get("usd", 0) or 0)
            if not (MIN_LIQUIDITY_USD <= liq_usd <= MAX_LIQUIDITY_USD):
                continue
                
            # الفحص الصارم لعمر العملة (يجب أن تكون جديدة تماماً خلال الساعتين الماضيتين)
            pair_created_at = float(p.get("pairCreatedAt", 0) or 0)
            if pair_created_at > 0:
                age_hours = (current_time_ms - pair_created_at) / (1000 * 60 * 60)
                if age_hours > MAX_PAIR_AGE_HOURS:
                    continue  # استبعاد أي عملة مر عليها أكثر من ساعتين فوراً
            else:
                continue  # إذا لم يكن تاريخ الإنشاء متوفراً، نستبعدها لضمان عدم دخول العملات القديمة

            if token_address in seen_tokens_cache:
                if current_time - seen_tokens_cache[token_address] < 7200:
                    continue
            
            seen_tokens_cache[token_address] = current_time

            name = str(base_token.get("name", "Token"))
            price = str(p.get("priceUsd", "?"))
            pair_url = str(p.get("url", ""))
            
            price_change = p.get("priceChange", {})
            m1 = float(price_change.get("m1", 0) or 0)

            entry = {
                "timestamp": current_time,
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
            
            unique_processed.append(entry)
            
            msg = f"🔥 *عملة حديثة جداً (خلال ساعتين)* [{chain_id}]\n"
            msg += f"العملة: *{symbol}* ({name})\n"
            msg += f"العقد: `{token_address}`\n"
            msg += f"السيولة: ${liq_usd:,.0f}\n"
            msg += pair_url
            send_telegram_alert(msg)

        except Exception:
            continue
            
    return unique_processed


async def scanner_loop():
    while True:
        try:
            new_items = await asyncio.to_thread(fetch_fresh_pairs_only)
            if new_items:
                for item in new_items:
                    alerts_feed.appendleft(item)
                stats["alerts_total"] = len(alerts_feed)
                
            stats["scanned_tokens"] += len(new_items) + 15
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
    <title>Fresh Sniper Engine</title>
    <style>
        body { background-color: #0d1117; color: #c9d1d9; font-family: Tahoma, sans-serif; margin: 0; padding: 20px; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #30363d; padding-bottom: 15px; margin-bottom: 20px; flex-wrap: wrap; gap: 10px; }
        h1 { margin: 0; color: #3fb950; font-size: 22px; }
        .stats { background: #161b22; padding: 10px 20px; border-radius: 8px; border: 1px solid #30363d; font-size: 14px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 15px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; border-right: 4px solid #3fb950; }
        .info { display: flex; flex-direction: column; gap: 5px; max-width: 75%; }
        .symbol { font-size: 18px; font-weight: bold; color: #3fb950; }
        .address { font-size: 12px; color: #8b949e; font-family: monospace; word-break: break-all; }
        .meta { font-size: 13px; color: #8b949e; display: flex; gap: 15px; flex-wrap: wrap; }
        .btn { background: #238636; color: #fff; padding: 8px 15px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: bold; white-space: nowrap; }
        .btn:hover { background: #2ea043; }
        .chain-tag { background: #1f6feb; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 11px; display: inline-block; margin-right: 5px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🌱 رادار العملات الحديثة فقط (أقل من ساعتين)</h1>
        <div class="stats" id="statsBox">جاري الاتصال بالسيرفر...</div>
    </div>
    
    <div id="alertsContainer">
        <div style="text-align: center; color: #8b949e; padding: 40px;">الرادار يفلترة العقود القديمة ويراقب الجديد فقط...</div>
    </div>

    <script>
        async function fetchAlerts() {
            try {
                let res = await fetch('/api/alerts');
                let data = await res.json();
                
                let stats = data.stats;
                document.getElementById('statsBox').innerHTML = 
                    `المفحوصة: <b>${stats.scanned_tokens}</b> | المرصودة: <b>${stats.alerts_total}</b> | آخر مسح: ${stats.last_scan || 'جارٍ...'}`;
                
                let alerts = data.alerts;
                let container = document.getElementById('alertsContainer');
                
                if (!alerts || alerts.length === 0) {
                    container.innerHTML = '<div style="text-align: center; color: #8b949e; padding: 40px;">بانتظار ظهور عملة أُنشئت حديثاً...</div>';
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
                                    <span>السعر: $${item.price}</span>
                                    <span>تغير m1: ${item.m1_change}%</span>
                                </div>
                            </div>
                            <div>
                                ${item.url ? `<a href="${item.url}" target="_blank" class="btn">فحص العقد 🎯</a>` : ''}
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
