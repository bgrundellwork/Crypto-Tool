def leverage_cap_from_vol(atr: float, price: float) -> int:
    """
    Conservative leverage cap based on ATR/price.
    You can tune later. These defaults are designed to keep you alive.
    """
    r = atr / price

    if r >= 0.006:   # 0.6% per candle = chaos
        return 1
    if r >= 0.004:   # high vol
        return 2
    if r >= 0.0025:  # normal
        return 3
    return 5         # low vol


def classify_confidence(trend: str, momentum: str, vol: str, vwap_ok: bool) -> str:
    score = 0
    if trend in ("bullish", "bearish"):
        score += 1
    if momentum == "strong":
        score += 1
    if vol == "low":
        score += 1
    if vwap_ok:
        score += 1

    if score >= 3:
        return "high"
    if score == 2:
        return "medium"
    return "low"


def compute_signal(
    coin: str,
    interval: str,
    trend: str,
    vol: str,
    momentum: str,
    price: float,
    vwap: float,
    atr: float,
) -> dict:
    """
    Institutional-style decision output.
    Returns bias + constraints (not a trade order).
    """
    reasons: list[str] = []

    vwap_dev_pct = ((price - vwap) / vwap) * 100 if vwap else 0.0

    # Location filter (VWAP)
    above_vwap = price > vwap
    below_vwap = price < vwap

    # No-trade conditions (risk kill-switch)
    no_trade = False
    if vol == "high":
        no_trade = True
        reasons.append("Volatility high: stand down")

    # Default action
    action = "neutral"
    vwap_ok = False

    # Long bias conditions
    if not no_trade and trend == "bullish":
        reasons.append("Bullish regime: price > EMA50")

        if above_vwap:
            vwap_ok = True
            reasons.append("Price above VWAP: continuation allowed")
        else:
            reasons.append("Price below VWAP: wait for reclaim")

        if momentum == "strong" and vwap_ok:
            action = "long_bias"
            reasons.append("Momentum strong: |z| > 2")
        elif momentum == "normal" and vwap_ok:
            action = "long_bias_low_conviction"
            reasons.append("Momentum normal: bias only")
        else:
            action = "neutral"

    # Short bias conditions
    if not no_trade and trend == "bearish":
        reasons.append("Bearish regime: price < EMA50")

        if below_vwap:
            vwap_ok = True
            reasons.append("Price below VWAP: continuation allowed")
        else:
            reasons.append("Price above VWAP: wait for reject")

        if momentum == "strong" and vwap_ok:
            action = "short_bias"
            reasons.append("Momentum strong: |z| > 2")
        elif momentum == "normal" and vwap_ok:
            action = "short_bias_low_conviction"
            reasons.append("Momentum normal: bias only")
        else:
            action = "neutral"

    # Confidence & leverage cap
    confidence = classify_confidence(trend, momentum, vol, vwap_ok)
    lev_cap = leverage_cap_from_vol(atr, price)

    return {
        "coin": coin,
        "interval": interval,
        "trend": trend,
        "volatility": vol,
        "momentum": momentum,
        "price": price,
        "vwap": vwap,
        "atr": atr,
        "vwap_deviation_pct": round(vwap_dev_pct, 4),
        "action": action,
        "confidence": confidence,
        "leverage_cap": lev_cap,
        "no_trade": no_trade,
        "reasons": reasons,
    }
