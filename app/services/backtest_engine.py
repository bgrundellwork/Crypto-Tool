from datetime import datetime
from typing import Any
from collections import defaultdict

from app.services.signal_engine import compute_signal
from app.services.ema import calculate_ema
from app.services.atr import calculate_atr
from app.services.vwap import calculate_vwap
from app.services.zscore import calculate_zscore, closes_to_returns
from app.services.regime import classify_regime
from app.services.vov import calculate_vov_from_atr, classify_vov


def build_regime_key(trend: str, volatility: str, momentum: str) -> str:
    """
    Compact regime identifier.
    Example: bullish_low_strong
    """
    return f"{trend}_{volatility}_{momentum}"


def _apply_costs(price: float, side: str, fee_bps: float, slippage_bps: float) -> float:
    cost_bps = fee_bps + slippage_bps
    mult = 1 + (cost_bps / 10000.0)
    if side == "long":
        return price * mult
    else:
        return price / mult


def _max_drawdown(equity: list[float]) -> float:
    peak = equity[0]
    mdd = 0.0
    for v in equity:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > mdd:
            mdd = dd
    return mdd * 100.0


async def run_backtest_on_candles(
    coin: str,
    interval: str,
    candles: list[dict[str, Any]],
    ema_period: int,
    atr_period: int,
    z_window: int,
    vov_window: int,
    initial_capital: float = 1000.0,
    fee_bps: float = 4.0,
    slippage_bps: float = 2.0,
    allow_low_conviction: bool = False,
) -> dict[str, Any]:

    if len(candles) < max(ema_period, atr_period + 2, z_window + 2, vov_window + 2) + 5:
        return {
            "status": "insufficient_data",
            "received_candles": len(candles),
        }

    closes = [c["close"] for c in candles]
    returns = closes_to_returns(closes)

    ema_series = calculate_ema(closes, ema_period)
    atr_series = calculate_atr(candles, atr_period)
    vwap_series = calculate_vwap(candles)
    z_series = calculate_zscore(returns, z_window)

    start_i = max(ema_period - 1, atr_period, z_window)

    capital = initial_capital
    equity = [capital]

    position = None
    trades = []

    # ✅ REGIME STATS (STEP 2)
    regime_stats = defaultdict(lambda: {
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "pnl": 0.0,
    })

    def record_trade(regime_key: str, pnl_pct: float):
        stats = regime_stats[regime_key]
        stats["trades"] += 1
        stats["pnl"] += pnl_pct
        if pnl_pct > 0:
            stats["wins"] += 1
        else:
            stats["losses"] += 1

    for i in range(start_i, len(candles)):
        price = closes[i]
        ts = candles[i]["timestamp"]

        ema = ema_series[i - (ema_period - 1)]
        atr = atr_series[i - atr_period]
        vwap = vwap_series[i]["vwap"]

        z = z_series[i - z_window] if (i - z_window) < len(z_series) else 0.0

        atr_upto = atr_series[: (i - atr_period + 1)]
        vov_value = calculate_vov_from_atr(atr_upto, window=vov_window)
        vov_state = classify_vov(vov_value, atr) if vov_value is not None else "stable"

        regime = classify_regime(price=price, ema=ema, atr=atr, zscore=z)
        regime_key = build_regime_key(
            regime["trend"],
            regime["volatility"],
            regime["momentum"],
        )

        signal = compute_signal(
            coin=coin,
            interval=interval,
            trend=regime["trend"],
            vol=regime["volatility"],
            momentum=regime["momentum"],
            price=price,
            vwap=vwap,
            atr=atr,
            vov_state=vov_state,
        )

        action = signal["action"]
        no_trade = signal["no_trade"]

        def is_long(a): return a in ("long_bias", "long_bias_low_conviction") if allow_low_conviction else a == "long_bias"
        def is_short(a): return a in ("short_bias", "short_bias_low_conviction") if allow_low_conviction else a == "short_bias"

        # EXIT
        if position:
            should_exit = (
                no_trade or
                (position["side"] == "long" and not is_long(action)) or
                (position["side"] == "short" and not is_short(action))
            )

            if should_exit:
                exit_price = _apply_costs(price, position["side"], fee_bps, slippage_bps)
                entry_price = position["entry_price"]

                pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
                if position["side"] == "short":
                    pnl_pct = -pnl_pct

                capital *= (1 + pnl_pct / 100.0)
                equity.append(capital)

                trades.append({
                    "side": position["side"],
                    "entry_ts": position["entry_ts"],
                    "entry_price": entry_price,
                    "exit_ts": ts,
                    "exit_price": exit_price,
                    "pnl_pct": pnl_pct,
                })

                record_trade(regime_key, pnl_pct)
                position = None
                continue

        # ENTRY
        if not position and not no_trade:
            if is_long(action):
                position = {
                    "side": "long",
                    "entry_price": _apply_costs(price, "long", fee_bps, slippage_bps),
                    "entry_ts": ts,
                }
            elif is_short(action):
                position = {
                    "side": "short",
                    "entry_price": _apply_costs(price, "short", fee_bps, slippage_bps),
                    "entry_ts": ts,
                }

    # FINAL CLOSE
    if position:
        price = closes[-1]
        ts = candles[-1]["timestamp"]
        exit_price = _apply_costs(price, position["side"], fee_bps, slippage_bps)
        entry_price = position["entry_price"]

        pnl_pct = ((exit_price - entry_price) / entry_price) * 100.0
        if position["side"] == "short":
            pnl_pct = -pnl_pct

        capital *= (1 + pnl_pct / 100.0)
        equity.append(capital)

        trades.append({
            "side": position["side"],
            "entry_ts": position["entry_ts"],
            "entry_price": entry_price,
            "exit_ts": ts,
            "exit_price": exit_price,
            "pnl_pct": pnl_pct,
        })

        record_trade(regime_key, pnl_pct)

    total_return = ((capital - initial_capital) / initial_capital) * 100.0
    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    win_rate = (wins / len(trades)) * 100.0 if trades else 0.0
    mdd = _max_drawdown(equity) if len(equity) > 1 else 0.0

    for stats in regime_stats.values():
        t = max(1, stats["trades"])
        stats["win_rate"] = stats["wins"] / t
        stats["expectancy"] = stats["pnl"] / t

    return {
        "status": "ok",
        "initial_capital": initial_capital,
        "final_capital": capital,
        "total_return_pct": total_return,
        "max_drawdown_pct": mdd,
        "trades": len(trades),
        "win_rate_pct": win_rate,
        "equity_curve": equity,
        "trade_list": trades,
        "regime_stats": regime_stats,
    }
