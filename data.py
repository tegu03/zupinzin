"""Free market-data collection (Binance public + alternative.me) and snapshot building.
NOTE: this covers PTE layers 2-5 from free sources. It is BLIND to live macro (Fed/DXY),
ETF flows, and news (the drivers MSE ranks highest). Add paid feeds (e.g. CoinGlass) here
later by adding fetchers and folding their values into build_snapshot()."""
import datetime
import httpx
from config import CONFIG

BINANCE = "https://fapi.binance.com"
FNG = "https://api.alternative.me/fng/?limit=1"
_OI_PERIODS = {"5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d"}
_HEADERS = {"User-Agent": "Mozilla/5.0 (pte-bot)"}


async def _get(client, url):
    r = await client.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


async def collect_market_data():
    sym, itv = CONFIG.binance_symbol, CONFIG.interval
    oi_period = itv if itv in _OI_PERIODS else "1h"
    async with httpx.AsyncClient(headers=_HEADERS) as c:
        return {
            "klines":  await _get(c, f"{BINANCE}/fapi/v1/klines?symbol={sym}&interval={itv}&limit=200"),
            "funding": await _get(c, f"{BINANCE}/fapi/v1/premiumIndex?symbol={sym}"),
            "oi":      await _get(c, f"{BINANCE}/futures/data/openInterestHist?symbol={sym}&period={oi_period}&limit=24"),
            "gls":     await _get(c, f"{BINANCE}/futures/data/globalLongShortAccountRatio?symbol={sym}&period=1h&limit=24"),
            "tls":     await _get(c, f"{BINANCE}/futures/data/topLongShortAccountRatio?symbol={sym}&period=1h&limit=24"),
            "taker":   await _get(c, f"{BINANCE}/futures/data/takerlongshortRatio?symbol={sym}&period=1h&limit=24"),
            "fng":     await _get(c, FNG),
        }


def _num(x):
    try:
        v = float(x)
        return v if v == v else None  # filter NaN
    except (TypeError, ValueError):
        return None


def _sma(a, n):
    return sum(a[-n:]) / n if len(a) >= n else None


def build_snapshot(raw, account):
    kl = raw.get("klines") or []
    closes = [v for v in (_num(k[4]) for k in kl) if v is not None]
    highs = [v for v in (_num(k[2]) for k in kl) if v is not None]
    lows = [v for v in (_num(k[3]) for k in kl) if v is not None]

    last = closes[-1] if closes else None
    h24 = max(highs[-24:]) if highs[-24:] else None
    l24 = min(lows[-24:]) if lows[-24:] else None
    c24 = closes[-25] if len(closes) >= 25 else (closes[0] if closes else None)
    chg24 = ((last - c24) / c24 * 100) if (last is not None and c24) else None
    sma20, sma50 = _sma(closes, 20), _sma(closes, 50)
    rng = ((last - l24) / (h24 - l24) * 100) if (last is not None and h24 is not None and l24 is not None and h24 > l24) else None
    trend = "mixed"
    if last is not None and sma20 is not None and sma50 is not None:
        if last > sma20 > sma50:
            trend = "up"
        elif last < sma20 < sma50:
            trend = "down"

    fund = raw.get("funding") or {}
    fr = _num(fund.get("lastFundingRate"))
    fpct = fr * 100 if fr is not None else None

    oi = raw.get("oi") or []
    oiL, oiF = (oi[-1], oi[0]) if oi else (None, None)
    oichg = None
    if oiL and oiF and _num(oiF.get("sumOpenInterest")):
        oichg = (_num(oiL["sumOpenInterest"]) - _num(oiF["sumOpenInterest"])) / _num(oiF["sumOpenInterest"]) * 100

    gls = (raw.get("gls") or [{}])[-1]
    tls = (raw.get("tls") or [{}])[-1]
    taker = (raw.get("taker") or [{}])[-1]
    fng = (raw.get("fng", {}).get("data") or [{}])[0]

    return {
        "symbol": CONFIG.binance_symbol,
        "interval": CONFIG.interval,
        "as_of": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "price": {
            "last": last, "change_24h_pct": chg24, "high_24h": h24, "low_24h": l24,
            "range_pos_pct": rng, "sma20": sma20, "sma50": sma50, "trend": trend,
        },
        "funding": {
            "rate_8h_pct": fpct,
            "annualized_pct": (fpct * 3 * 365) if fpct is not None else None,
            "next_funding_time": fund.get("nextFundingTime"),
        },
        "open_interest": {
            "current_btc": _num(oiL.get("sumOpenInterest")) if oiL else None,
            "current_usd": _num(oiL.get("sumOpenInterestValue")) if oiL else None,
            "change_24h_pct": oichg,
        },
        "long_short": {
            "global_ratio": _num(gls.get("longShortRatio")),
            "global_long_pct": (_num(gls.get("longAccount")) * 100) if _num(gls.get("longAccount")) is not None else None,
            "top_trader_ratio": _num(tls.get("longShortRatio")),
            "taker_buy_sell_ratio": _num(taker.get("buySellRatio")),
        },
        "sentiment": {"fear_greed": _num(fng.get("value")), "label": fng.get("value_classification")},
        "account": account,
    }
