import math


def calculate_zscore(values: list[float], window: int) -> list[float]:
    """
    Rolling z-score of a series:
      z = (x - mean(window)) / std(window)

    Returns a list aligned to the input series starting at index (window-1).
    """
    if window <= 1 or len(values) < window:
        return []

    out: list[float] = []

    for i in range(window - 1, len(values)):
        w = values[i - window + 1 : i + 1]
        mean = sum(w) / window

        # population std (stable enough for research features)
        var = sum((x - mean) ** 2 for x in w) / window
        std = math.sqrt(var)

        if std == 0:
            out.append(0.0)
        else:
            out.append((values[i] - mean) / std)

    return out


def closes_to_returns(closes: list[float]) -> list[float]:
    """
    Convert close prices to simple returns:
      r_t = (close_t / close_{t-1}) - 1

    Returns length = len(closes)-1
    """
    if len(closes) < 2:
        return []

    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        curr = closes[i]
        if prev == 0:
            rets.append(0.0)
        else:
            rets.append((curr / prev) - 1.0)
    return rets
