import math


def rolling_std(values: list[float], window: int) -> list[float]:
    if window <= 1 or len(values) < window:
        return []

    out: list[float] = []
    for i in range(window - 1, len(values)):
        w = values[i - window + 1 : i + 1]
        mean = sum(w) / window
        var = sum((x - mean) ** 2 for x in w) / window
        out.append(math.sqrt(var))
    return out


def calculate_vov_from_atr(atr_values: list[float], window: int = 20) -> float | None:
    """
    VoV = rolling std of ATR over `window`.
    Returns the latest VoV value (scalar) or None if insufficient data.
    """
    std_series = rolling_std(atr_values, window)
    if not std_series:
        return None
    return std_series[-1]


def classify_vov(vov: float, atr: float) -> str:
    """
    Normalize VoV by ATR to get a scale-free instability measure.
    vov_ratio = vov / atr

    Returns: stable / rising / unstable
    """
    if atr <= 0:
        return "stable"

    ratio = vov / atr

    # Conservative defaults (tune later)
    if ratio < 0.15:
        return "stable"
    elif ratio < 0.30:
        return "rising"
    return "unstable"
