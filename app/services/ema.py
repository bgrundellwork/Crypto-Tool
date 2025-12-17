def calculate_ema(prices: list[float], period: int) -> list[float]:
    """
    Calculate EMA for a list of prices.
    Returns list aligned with prices (first EMA starts at index period-1).
    """
    if len(prices) < period:
        return []

    ema_values = []
    multiplier = 2 / (period + 1)

    # Start EMA with SMA
    sma = sum(prices[:period]) / period
    ema_values.append(sma)

    for price in prices[period:]:
        ema = (price - ema_values[-1]) * multiplier + ema_values[-1]
        ema_values.append(ema)

    return ema_values
