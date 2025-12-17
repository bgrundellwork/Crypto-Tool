def leverage_cap_from_vol(atr: float, price: float) -> int:
    """
    Conservative leverage cap based on ATR/price.
    Designed to keep leverage traders alive during regime changes.
    """
    r = atr / price

    if r >= 0.006:   # ~0.6% per candle → chaos / liquidation risk
        return 1
    if r >= 0.004:   # high volatility
        return 2
    if r >= 0.0025:  # normal volatility
        return 3
    return 5         # low volatility


def classify_confidence(
    trend: str,
    momentum: str,
    vol: str,
    vwap_ok: bool,
    vov_state: str,
) -> str:
    """
    Confidence is about how reliable the *state classification* is,
    not whether a trade should be taken.
    """
    score = 0

    if trend in ("bullish", "bearish"):
        score += 1
    if momentum == "strong":
        score += 1
    if vol == "low":
        score += 1
    if vwap_ok:
        score += 1
    if vov_state == "stable":
        score += 1

    if score >= 4:
        return "high"
    if score >= 2:
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
    vov_state: str = "stable",
) -> dict:
    """
    Institutional decision engine.
    Outputs bias + constraints — NEVER an order.
    """

    reasons: list[str] = []

    # VWAP deviation (%)
    vwap_dev_pct = ((price - vwap) / vwap) * 100 if vwap else 0.0

    # Location
    above_vwap = price > vwap
    below_vwap = price < vwap

    # ----------------------------
    # RISK KILL SWITCHES
    # ----------------------------
    no_trade = False

    if vol == "high":
        no_trade = True
        reasons.append("Volatility high: stand down")

    if vov_state == "unstable":
        no_trade = True
        reasons.append("VoV unstable: volatility regime shifting (kill switch)")

    # ----------------------------
    # DEFAULT STATE
    # ----------------------------
    action = "neutral"
    vwap_ok = False

    # ----------------------------
    # LONG BIAS LOGIC
    # ----------------------------
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

    # ----------------------------
    # SHORT BIAS LOGIC
    # ----------------------------
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

    # ----------------------------
    # LEVERAGE CONTROL
    # ----------------------------
    lev_cap = leverage_cap_from_vol(atr, price)

    if vov_state == "rising":
        lev_cap = max(1, lev_cap - 1)
        reasons.append("VoV rising: reduced leverage cap")

    # ----------------------------
    # CONFIDENCE
    # ----------------------------
    confidence = classify_confidence(
        trend=trend,
        momentum=momentum,
        vol=vol,
        vwap_ok=vwap_ok,
        vov_state=vov_state,
    )

    # ----------------------------
    # FINAL OUTPUT
    # ----------------------------
    return {
        "coin": coin,
        "interval": interval,
        "trend": trend,
        "volatility": vol,
        "momentum": momentum,
        "vov_state": vov_state,
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
