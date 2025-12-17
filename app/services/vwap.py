def calculate_vwap(candles: list[dict]) -> list[dict]:
    """
    Calculate VWAP from candle data.
    Candles must include: high, low, close, volume, timestamp
    Returns VWAP aligned to each candle.
    """
    cumulative_pv = 0.0
    cumulative_volume = 0.0

    vwap_series = []

    for c in candles:
        typical_price = (c["high"] + c["low"] + c["close"]) / 3
        volume = c["volume"]

        cumulative_pv += typical_price * volume
        cumulative_volume += volume

        vwap = cumulative_pv / cumulative_volume if cumulative_volume > 0 else 0.0

        vwap_series.append(
            {
                "timestamp": c["timestamp"],
                "vwap": vwap,
            }
        )

    return vwap_series
