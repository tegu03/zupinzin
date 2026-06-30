"""DETERMINISTIC Risk Governor. The AI proposes; this code disposes.
Re-computes R:R from scratch, sizes the position from the STOP (fixed fractional),
checks trade geometry, and enforces hard gates + the daily-loss kill switch.
Nothing here trusts the model's math."""
from config import CONFIG


def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def evaluate(pte, mse, snapshot):
    cfg = CONFIG
    acc = snapshot.get("account", {})
    equity = _num(acc.get("equity_usd")) or cfg.initial_capital
    reasons, approved = [], True

    signal = pte.get("signal")
    if signal not in ("long", "short"):
        approved = False
        reasons.append(f"Signal not actionable: {signal}")

    regime = pte.get("regime") or mse.get("pte_layer1_input")
    if regime == "chop":
        approved = False
        reasons.append("Regime chop/unclear -> NO-TRADE")

    entry_obj = pte.get("entry") or {}
    entry = _num(entry_obj.get("price"))
    if entry is None:
        zone = entry_obj.get("zone") or [None]
        entry = _num(zone[0])
    stop = _num(pte.get("invalidation"))
    targets = pte.get("targets") or []
    tp1 = _num(targets[0]) if len(targets) > 0 else None
    tp2 = _num(targets[1]) if len(targets) > 1 else None

    if entry is None or stop is None:
        approved = False
        reasons.append("Missing entry or invalidation")

    rr = stop_dist = risk_usd = notional = base_amount = side = None
    if entry is not None and stop is not None and tp1 is not None:
        risk_dist = abs(entry - stop)
        reward_dist = abs(tp1 - entry)
        rr = reward_dist / risk_dist if risk_dist > 0 else 0
        if signal == "long" and not (stop < entry < tp1):
            approved = False
            reasons.append("Long geometry invalid (need stop<entry<tp1)")
        if signal == "short" and not (stop > entry > tp1):
            approved = False
            reasons.append("Short geometry invalid (need stop>entry>tp1)")
        if rr < cfg.min_rr:
            approved = False
            reasons.append(f"R:R {rr:.2f} < min {cfg.min_rr}")
        # size from stop (fixed fractional)
        stop_dist = risk_dist / entry
        risk_usd = equity * cfg.risk_pct
        notional = risk_usd / stop_dist if stop_dist > 0 else 0
        cap = equity * cfg.max_leverage
        if notional > cap:
            notional = cap
            reasons.append(f"Notional capped at {cfg.max_leverage}x equity")
        base_amount = notional / entry if entry > 0 else 0
        side = "buy" if signal == "long" else "sell"
    elif signal in ("long", "short"):
        approved = False
        reasons.append("Missing TP1 for R:R / sizing")

    # event-risk note from the model (soft)
    ev = str(pte.get("event_risk") or "")
    if ev and any(w in ev.lower() for w in ("high-impact", "imminent", "within hours", "fomc", "cpi", "nfp", "expiry")):
        reasons.append(f"Event risk noted: {ev}")

    # kill switch: daily loss limit (uses baseline tracked in exchange.get_account)
    dp = _num(acc.get("daily_pnl_pct"))
    if dp is not None and dp <= -(cfg.daily_loss_limit_pct * 100):
        approved = False
        reasons.append(f"KILL SWITCH: daily {dp:.2f}% <= -{cfg.daily_loss_limit_pct * 100:.1f}%")

    if not reasons:
        reasons.append("All gates passed")

    return {
        "approved": bool(approved and signal in ("long", "short")),
        "signal": signal,
        "side": side,
        "regime": regime,
        "confidence_pct": pte.get("confidence_pct"),
        "entry": entry,
        "stop": stop,
        "tp1": tp1,
        "tp2": tp2,
        "entry_type": entry_obj.get("type") or "limit",
        "rr": round(rr, 2) if rr is not None else None,
        "stop_distance_pct": round(stop_dist * 100, 3) if stop_dist is not None else None,
        "risk_usd": round(risk_usd, 2) if risk_usd is not None else None,
        "notional_usd": round(notional, 2) if notional is not None else None,
        "base_amount": round(base_amount, 6) if base_amount is not None else None,
        "equity_usd": round(equity, 2),
        "market_index": cfg.market_index,
        "dry_run": cfg.dry_run,
        "reasons": reasons,
        "abstain_reason": pte.get("abstain_reason") or "",
        "flip_if": pte.get("flip_if") or "",
        "counter_thesis": pte.get("counter_thesis") or "",
        "funding_note": pte.get("funding_note") or "",
    }
