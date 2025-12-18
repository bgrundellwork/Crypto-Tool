TIMEFRAME_PROFILES = {
    "5m": {
        # scaled from 15m profile (same “time coverage” but 3x more candles)
        "ema": 90,   # 90 * 5m = 7.5h  (same as 30 * 15m)
        "atr": 30,   # 30 * 5m = 2.5h  (same as 10 * 15m)
        "z": 96,     # 96 * 5m = 8h    (same as 32 * 15m)
        "vov": 42,   # 42 * 5m = 3.5h  (same as 14 * 15m)
    },
    "15m": {
        "ema": 30,
        "atr": 10,
        "z": 32,
        "vov": 14,
    },
    "1h": {
        "ema": 12,
        "atr": 6,
        "z": 16,
        "vov": 8,
    },
    "1d": {
        "ema": 5,
        "atr": 3,
        "z": 5,
        "vov": 3,
    },
}
