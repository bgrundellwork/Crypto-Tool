def calculate_atr(candles: list[dict], period: int = 14) -> list[float]:
    """
    Calculate ATR from candle data.
    Candles must contain: high, low, close
    Returns ATR values aligned to candles (starts at index period)
    """
    if len(candles) < period + 1:
        return []

    true_ranges = []

    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    # Initial ATR = simple average of first TRs
    atr_values = []
    first_atr = sum(true_ranges[:period]) / period
    atr_values.append(first_atr)

    # EMA-style smoothing
    multiplier = 1 / period
    for tr in true_ranges[period:]:
        atr = (tr * multiplier) + (atr_values[-1] * (1 - multiplier))
        atr_values.append(atr)

    return atr_values
