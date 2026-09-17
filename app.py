"""
Smart Money & First-Tick Ignition Sniper (Pump.fun Direct Live Stream Edition)
رادار الشرارة الأولى - الاتصال المباشر بلحظة إنشاء وتوليد الشمعة الأولى
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

# إعدادات رصد البدايات الصاروخية المبكرة جداً
MIN_LIQUIDITY_USD = float(os.environ.get("MIN_LIQUIDITY_USD", 1))       
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 0.3))              # فحص فائق السرعة كل 300 جزء من الثانية
MAX_ALERTS_STORED = 100
ALERT_COOLDOWN_SECONDS = 300                                           

IGNORED_TOKENS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
}

app = FastAPI(title="Pump.fun Direct Sniper")

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
        }, timeout=1)
    except Exception:
        pass


def fetch_pump_fresh_tokens():
    pairs_list = []
    
    # المصدر المباشر الأول: أحدث العملات المنشأة لحظياً على منصة Pump.fun (بدون أي تأخير في الفهرسة)
    try:
        r = requests.get("https://client-api-2-atac.pump.fun/coins/latest?offset=0&limit=20&sort=created_timestamp&order=DESC", timeout=2)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                for coin in data:
                    mint = coin.get("mint")
                    symbol = str(coin.get("symbol", "")).upper()
                    name = str(coin.get("name", ""))
                    created_timestamp = coin.get("created_timestamp", 0)
                    
                    # التأكد أن العملة جديدة كلياً (أقل من 15 دقيقة)
                    if created_timestamp:
                        age_min = (time.time() * 1000 - created_timestamp) / (1000 * 60)
                        if age_min > 15:
                            continue

                    # تحويل بيانات العملة لتتطابق مع هيكل الرادار مع رابط مباشر لـ DexScreener و Pump.fun
                    if mint and mint not in IGNORED_TOKENS:
                        pairs_list.append({
                            "chainId": "SOLANA",
                            "baseToken": {
                                "address": mint,
                                "symbol": symbol,
                                "name": name
                            },
                            "priceUsd": str(coin.get("usd_market_cap", 0) / 1000000 if coin.get("usd_market_cap") else "0.0001"),
                            "liquidity": {"usd": float(coin.get("raydium_pool") and 500 or 50)},
                            "volume": {"h1": float(coin.get("market_cap", 1000) / 10)},
                            "url": f"https://dexscreener.com/solana/{mint}"
                        })
    except Exception:
        pass

    # المصدر المباشر الثاني: أحدث أزواج Raydium و Solana الطازجة عبر DexScreener (Latest Pairs Direct Feed)
    try:
        r2 = requests.get("https://api.dexscreener.com/latest/dex/tokens/solana", timeout=2)
        # بدلاً من ذلك، نستخدم جلب التوكنات الجديدة مباشرة من مسار الأحدث
        r_new = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=2)
        if r_new.status_code == 200:
            items = r_new.json()
            if isinstance(items, list):
                addrs = [i.get("tokenAddress") for i in items if i.get("chainId") == "solana" or i.get("tokenAddress")]
                if addrs:
                    chunk = ",".join(addrs[:15])
                    r_p = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{chunk}", timeout=2)
                    if r_p.status_code == 200:
                        p_json = r_p.json().get("pairs", [])
                        if isinstance(p_json, list):
                            pairs_list.extend(p_json)
    except Exception:
        pass

    seen = set()
    unique = []
    for p in pairs_list:
        try:
            base_token = p.get("baseToken", {})
            token_address = base_token.get("address")
            symbol = str(base_token.get("symbol", "")).upper()
            
            if not token_address or token_address in IGNORED_TOKENS:
                continue
                
            if token_address not in seen:
                seen.add(token_address)
                unique.append(p)
        except Exception:
            continue
            
    return unique


def analyze_and_push(pair):
    try:
        if not pair:
            return

        chain_id = str(pair.get("chainId", "SOLANA")).upper()
        base_token = pair.get("baseToken", {})
        token_address = str(base_token.get("address", ""))
        symbol = str(base_token.get("symbol", "")).upper()
        
        if not token_address or token_address in IGNORED_TOKENS:
            return

        liq_usd = float(pair.get("liquidity", {}).get("usd", 50) or 50)
        h1_vol = float(pair.get("volume", {}).get("h1", 100) or 100)

        now = time.time()
        if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
            return
        last_alert_time[token_address] = now

        name = str(base_token.get("name", "New Token"))
        price = str(pair.get("priceUsd", "0.001"))
        pair_url = str(pair.get("url", f"https://dexscreener.com/solana/{token_address}"))

        entry = {
            "timestamp": now,
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "chain": chain_id,
            "symbol": symbol,
            "name": name,
            "token_address": token_address,
            "price": price,
            "liquidity": liq_usd,
            "volume": h1_vol,
            "url": pair_url
        }
        
        alerts_feed.appendleft(entry)
        stats["alerts_total"] = len(alerts_feed)

        msg = "🔥 *شرارة ولادة الشمعة الأولى مباشرة!* [" + chain_id + "]\n"
        msg += "العملة: *" + symbol + "* (" + name + ")\n"
        msg += "العقد: `" + token_address + "`\n"
        msg += "السيولة المبكرة: $" + f"{liq_usd:,.0f}" + "\n"
        msg += pair_url
        
        send_telegram_alert(msg)
    except Exception:
        pass


async def scanner_loop():
    while True:
        try:
            pairs = await asyncio.to_thread(fetch_pump_fresh_tokens)
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
    <title>Pump.fun Direct Sniper</title>
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
        <h1>⚡ رادار الشرارة الأولى (البث المباشر الفوري Pump.fun)</h1>
        <div class="stats" id="statsBox">جاري الاتصال بالسيرفر...</div>
    </div>
    
    <div id="alertsContainer">
        <div style="text-align: center; color: #8b949e; padding: 40px;">جاري التقاط التوكنات في ثانية ولادتها الأولى...</div>
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
                    container.innerHTML = '<div style="text-align: center; color: #8b949e; padding: 40px;">بانتظار لحظة انطلاق الصاروخ الأول في السوق...</div>';
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
                                    <span style="color: #3fb950; font-size: 12px; font-weight: bold; margin-right: 10px;">[وقت ولادة الشرارة: ${item.time}]</span>
                                </div>
                                <div class="address">العقد: ${item.token_address}</div>
                                <div class="meta">
                                    <span>السيولة: <b>$${item.liquidity.toLocaleString()}</b></span>
                                    <span>الحالة: <span class="ignition">الشمعة الأولى اللحظية ⚡</span></span>
                                    <span>السعر: $${item.price}</span>
                                </div>
                            </div>
                            <div>
                                ${item.url ? `<a href="${item.url}" target="_blank" class="btn">قنص الانطلاقة 🎯</a>` : ''}
                            </div>
                        </div>
                    `;
                });
                container.innerHTML = html;
            } catch (e) {
                console.error(e);
            }
        }
        
        setInterval(fetchAlerts, 2000);
        fetchAlerts();
    </script>
</body>
</html>
    """
