def analyze_first_spark(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown").upper()
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    # التركيز على حركة الـ 5 دقائق الأولى بدلاً من الساعة لتفادي التأخير
    txns = pair.get("txns", {})
    m5 = txns.get("m5", {})
    m5_buys = m5.get("buys", 0) or 0
    m5_sells = m5.get("sells", 0) or 0
    
    m5_vol = float(pair.get("volume", {}).get("m5", 0) or 0)
    
    price_change = pair.get("priceChange", {})
    m5_change = float(price_change.get("m5", 0) or 0)

    # شروط الشرارة الأولى اللحظية: صعود قوي في 5 دقائق مع سيطرة واضحة للشراء
    if m5_change < 3.0 or m5_buys <= m5_sells:
        return

    now = time.time()
    if now - last_alert_time.get(token_address, 0) < ALERT_COOLDOWN_SECONDS:
        return
    last_alert_time[token_address] = now

    symbol = pair.get("baseToken", {}).get("symbol", "?")
    name = pair.get("baseToken", {}).get("name", "Token")
    price = pair.get("priceUsd", "?")
    mcap = pair.get("fdv", pair.get("marketCap", "?"))
    pair_url = pair.get("url", "")

    status_text = f"⚡ شرارة لحظية [صعود 5m: +{m5_change:.1f}%] (شراء: {m5_buys} | بيع: {m5_sells})"

    entry = {
        "type": "first_spark",
        "time": datetime.now(timezone.utc).isoformat(),
        "chain": chain_id,
        "symbol": symbol,
        "name": name,
        "token_address": token_address,
        "price": price,
        "mcap": mcap,
        "liquidity": liq_usd,
        "volume": m5_vol,
        "buys": m5_buys,
        "sells": m5_sells,
        "url": pair_url,
        "safety": status_text,
        "strength": float(m5_vol * (1 + m5_change))
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🎯 *رصد شرارة الانطلاق السريع* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"حجم 5د: ${m5_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)
