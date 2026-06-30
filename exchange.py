"""Lighter integration: account reads + L2-signed order execution, in-process.
The native Go signer runs fine on Linux (your Ubuntu VPS). dry_run is honored:
when on, NO order is signed/sent.

VERIFY ONCE on first run (DEBUG _raw block is logged in get_account):
  - the *_KEYS field mappings below (if a value comes back None)
  - PRICE/SIZE decimals via find_account.py
  - the SignerClient order-type constants (if create_order errors)
"""
import time
import json
import contextlib
import logging

import lighter
from config import CONFIG

log = logging.getLogger("pte-bot.exchange")

# --- account field mapping (varies by SDK version; tune if a value is None) ---
COLLATERAL_KEYS = ["collateral", "available_balance", "available_collateral", "cross_asset_value"]
ACCOUNT_VALUE_KEYS = ["total_asset_value", "account_value", "portfolio_value", "equity"]
POS_SIZE_KEYS = ["position", "position_size", "size", "base_amount"]
POS_ENTRY_KEYS = ["avg_entry_price", "entry_price", "average_entry_price"]
POS_UPNL_KEYS = ["unrealized_pnl", "unrealised_pnl", "uPnl", "upnl"]
POS_SIGN_KEYS = ["sign", "side", "direction"]
POS_MARKET_KEYS = ["market_id", "market_index", "symbol"]


def _pick(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]
    return default


def _to_dict(obj):
    for m in ("model_dump", "to_dict", "dict"):
        if hasattr(obj, m):
            with contextlib.suppress(Exception):
                return getattr(obj, m)()
    return obj if isinstance(obj, dict) else {}


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime())


def _daily_baseline(equity):
    """Today's starting equity (resets 00:00 UTC), persisted for the kill switch."""
    try:
        with open(CONFIG.state_file) as f:
            s = json.load(f)
    except Exception:
        s = {}
    if s.get("date") != _today():
        s = {"date": _today(), "baseline_equity": equity}
        with contextlib.suppress(Exception):
            with open(CONFIG.state_file, "w") as f:
                json.dump(s, f)
    return float(s.get("baseline_equity", equity))


def _const(name, fallback):
    return int(getattr(lighter.SignerClient, name, fallback))


OT_LIMIT = _const("ORDER_TYPE_LIMIT", 0)
OT_MARKET = _const("ORDER_TYPE_MARKET", 1)
OT_SL = _const("ORDER_TYPE_STOP_LOSS", 2)
OT_TP = _const("ORDER_TYPE_TAKE_PROFIT", 4)
TIF_IOC = _const("ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL", 0)
TIF_GTT = _const("ORDER_TIME_IN_FORCE_GOOD_TILL_TIME", 1)


class Exchange:
    def __init__(self):
        self.api = None
        self.account_api = None
        self.order_api = None
        self.signer = None

    async def start(self):
        self.api = lighter.ApiClient(lighter.Configuration(host=CONFIG.lighter_base_url))
        self.account_api = lighter.AccountApi(self.api)
        self.order_api = lighter.OrderApi(self.api)
        if CONFIG.lighter_private_key:
            self.signer = lighter.SignerClient(
                url=CONFIG.lighter_base_url,
                api_private_keys={CONFIG.lighter_api_key_index: CONFIG.lighter_private_key},
                account_index=CONFIG.lighter_account_index,
            )
        log.info("exchange ready (signer=%s)", "ON" if self.signer else "OFF read-only")

    async def close(self):
        if self.signer:
            with contextlib.suppress(Exception):
                await self.signer.close()
        if self.api:
            with contextlib.suppress(Exception):
                await self.api.close()

    # ---- helpers ----
    def _int_price(self, p):
        return int(round(float(p) * (10 ** CONFIG.price_decimals)))

    def _int_size(self, q):
        return int(round(float(q) * (10 ** CONFIG.size_decimals)))

    def _coi(self):
        return int(time.time() * 1000) % (2 ** 47)

    async def _place(self, coi, size_int, price_int, is_ask, order_type, tif,
                     reduce_only=False, trigger_price=0, expiry=0):
        try:
            tx, tx_hash, err = await self.signer.create_order(
                market_index=CONFIG.market_index,
                client_order_index=coi,
                base_amount=size_int,
                price=price_int,
                is_ask=is_ask,
                order_type=order_type,
                time_in_force=tif,
                reduce_only=reduce_only,
                trigger_price=trigger_price,
                order_expiry=expiry,
            )
            if err:
                return {"ok": False, "error": str(err)}
            return {"ok": True, "tx_hash": str(tx_hash)}
        except TypeError as e:
            return {"ok": False, "error": f"create_order signature mismatch ({e}); check your SDK version"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # ---- account ----
    async def get_account(self):
        fallback = {
            "base_capital_usd": CONFIG.initial_capital, "equity_usd": CONFIG.initial_capital,
            "available_usd": CONFIG.initial_capital, "unrealized_pnl_usd": 0.0,
            "realized_pnl_today_usd": 0.0, "daily_pnl_pct": 0.0, "positions": [], "source": "fallback",
        }
        try:
            acc_obj = await self.account_api.account(by="index", value=str(CONFIG.lighter_account_index))
            raw = _to_dict(acc_obj)
            node = raw["accounts"][0] if isinstance(raw.get("accounts"), list) and raw["accounts"] else raw

            collateral = float(_pick(node, COLLATERAL_KEYS, 0) or 0)
            positions, u_pnl = [], 0.0
            for p in (node.get("positions") or []):
                pd = _to_dict(p) if not isinstance(p, dict) else p
                size = float(_pick(pd, POS_SIZE_KEYS, 0) or 0)
                if size == 0:
                    continue
                up = float(_pick(pd, POS_UPNL_KEYS, 0) or 0)
                u_pnl += up
                positions.append({
                    "market": _pick(pd, POS_MARKET_KEYS), "size": size,
                    "entry_price": _pick(pd, POS_ENTRY_KEYS), "sign": _pick(pd, POS_SIGN_KEYS),
                    "unrealized_pnl_usd": up,
                })

            equity = _pick(node, ACCOUNT_VALUE_KEYS)
            equity = float(equity) if equity is not None else (collateral + u_pnl)

            baseline = _daily_baseline(equity)
            today_pnl = equity - baseline
            return {
                "base_capital_usd": CONFIG.initial_capital,
                "equity_usd": round(equity, 2),
                "available_usd": round(collateral, 2),
                "unrealized_pnl_usd": round(u_pnl, 2),
                "realized_pnl_today_usd": round(today_pnl, 2),
                "daily_pnl_pct": round((today_pnl / baseline * 100) if baseline else 0.0, 2),
                "total_pnl_usd": round(equity - CONFIG.initial_capital, 2),
                "positions": positions,
                "source": "lighter",
                "_raw": node,  # inspect once, then tune *_KEYS above
            }
        except Exception as e:
            log.warning("get_account failed, using fallback: %s", e)
            fallback["error"] = f"{type(e).__name__}: {e}"
            return fallback

    # ---- execution ----
    async def execute(self, decision):
        out = {"ok": False, "dry_run": decision["dry_run"], "side": decision["side"],
               "sl": None, "tp1": None, "warning": None}

        if decision["dry_run"]:
            out.update({"ok": True, "tx_hash": "DRYRUN-" + str(self._coi()), "note": "dry_run -> no order sent"})
            return out
        if self.signer is None:
            out["error"] = "Signer not initialized (set LIGHTER_PRIVATE_KEY)."
            return out

        size_int = self._int_size(decision["base_amount"])
        if size_int <= 0:
            out["error"] = f"base_amount rounds to 0 at SIZE_DECIMALS={CONFIG.size_decimals}"
            return out

        is_ask = decision["side"] == "sell"
        entry = decision["entry"]
        if decision["entry_type"] == "market":
            worst = entry * (1 + CONFIG.mkt_slippage) if not is_ask else entry * (1 - CONFIG.mkt_slippage)
            res = await self._place(self._coi(), size_int, self._int_price(worst), is_ask, OT_MARKET, TIF_IOC)
        else:
            exp = int((time.time() + 7 * 24 * 3600) * 1000)
            res = await self._place(self._coi(), size_int, self._int_price(entry), is_ask, OT_LIMIT, TIF_GTT, expiry=exp)
        out.update(res)
        if not res.get("ok"):
            return out

        if CONFIG.place_sl_tp:
            opp = not is_ask
            exp = int((time.time() + 7 * 24 * 3600) * 1000)
            if decision.get("stop"):
                out["sl"] = await self._place(self._coi(), size_int, self._int_price(decision["stop"]),
                                              opp, OT_SL, TIF_GTT, reduce_only=True,
                                              trigger_price=self._int_price(decision["stop"]), expiry=exp)
            if decision.get("tp1"):
                out["tp1"] = await self._place(self._coi(), size_int, self._int_price(decision["tp1"]),
                                               opp, OT_TP, TIF_GTT, reduce_only=True,
                                               trigger_price=self._int_price(decision["tp1"]), expiry=exp)
            if out.get("sl") and not out["sl"].get("ok"):
                out["warning"] = "ENTRY PLACED but STOP-LOSS FAILED: " + str(out["sl"].get("error")) \
                                 + " -- manage the stop manually or fix trigger params."
        return out
