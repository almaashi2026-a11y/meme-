def analyze_first_spark(pair):
    if not pair:
        return

    chain_id = pair.get("chainId", "unknown").upper()
    token_address = pair.get("baseToken", {}).get("address", "")
    if not token_address:
        return

    # التأكد من وجود سيولة تشغيلية كافية لتجنب العملات الوهمية
    liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
    if liq_usd < MIN_LIQUIDITY_USD:
        return

    # قراءة الصفقات وحجم التداول لآخر 5 دقائق (القلب النابض للرصد السريع)
    txns = pair.get("txns", {})
    m5 = txns.get("m5", {})
    m5_buys = m5.get("buys", 0) or 0
    m5_sells = m5.get("sells", 0) or 0
    
    m5_vol = float(pair.get("volume", {}).get("m5", 0) or 0)
    if m5_vol < MIN_VOLUME_USD:
        return

    price_change = pair.get("priceChange", {})
    m5_change = float(price_change.get("m5", 0) or 0)

    # ---------------------------------------------------------
    # شروط "الشراء القوي جداً" (Heavy Buying & Aggressive Accumulation)
    # ---------------------------------------------------------
    # 1. أن يكون التغير السعري في أول 5 دقائق إيجابياً وقوياً (أكبر من 5%) ولكن غير متأخر (أقل من 60%)
    if m5_change < 5.0 or m5_change > 60.0:
        return

    # 2. الهيمنة المطلقة للشراء: صفقات الشراء يجب أن تكون أضعاف البيع (مثلاً الشراء أضعاف أو بنسبة هائلة)
    total_txns = m5_buys + m5_sells
    if total_txns < 5:
        return
    
    buy_ratio = m5_buys / total_txns
    if buy_ratio < 0.75:  # يجب أن تكون نسبة الصفقات الخضراء (الشراء) 75% على الأقل
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

    status_text = f"🚨 **شراء قوي جداً [صعود 5م: +{m5_change:.1f}%]** (نسبة الشراء: {buy_ratio*100:.0f}% | شراء: {m5_buys} - بيع: {m5_sells})"

    entry = {
        "type": "heavy_buy_spark",
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
        "strength": float(m5_vol * buy_ratio * (1 + m5_change))
    }
    alerts_feed.appendleft(entry)
    stats["alerts_total"] += 1

    msg = (
        f"🔥 *رصد شراء قوي واختراق مبكر* [{chain_id}]\n"
        f"العملة: *{symbol}* ({name})\n"
        f"العقد: `{token_address}`\n"
        f"الحالة: {status_text}\n"
        f"حجم 5د: ${m5_vol:,.0f} | السيولة: ${liq_usd:,.0f}\n"
        f"السعر: ${price}\n"
        f"{pair_url}"
    )
    send_telegram_alert(msg)
