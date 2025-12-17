def classify_trend(price: float, ema: float) -> str:
    if price > ema:
        return "bullish"
    elif price < ema:
        return "bearish"
    return "neutral"


def classify_volatility(atr: float, price: float) -> str:
    ratio = atr / price

    if ratio < 0.0015:
        return "low"
    elif ratio < 0.003:
        return "normal"
    return "high"


def classify_momentum(z: float) -> str:
    if abs(z) > 2.0:
        return "strong"
    elif abs(z) < 0.5:
        return "weak"
    return "normal"


def classify_regime(
    price: float,
    ema: float,
    atr: float,
    zscore: float,
) -> dict:
    return {
        "trend": classify_trend(price, ema),
        "volatility": classify_volatility(atr, price),
        "momentum": classify_momentum(zscore),
    }
