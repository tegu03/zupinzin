"""Entry point. Runs the full pipeline on a fixed interval, forever.
Pipeline per cycle:
  account -> market data -> snapshot -> MSE regime -> PTE thesis
  -> deterministic Risk Governor -> (execute if approved) -> Telegram
"""
import asyncio
import contextlib
import logging

from config import CONFIG
from data import collect_market_data, build_snapshot
from llm import classify_regime, analyze_trade
from risk import evaluate
from exchange import Exchange
from notify import send, format_trade, format_notrade

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("pte-bot")


async def run_cycle(ex: Exchange):
    account = await ex.get_account()
    account.pop("_raw", None)  # keep logs/messages clean (inspect once via DEBUG if needed)
    raw = await collect_market_data()
    snap = build_snapshot(raw, account)
    log.info("price=%s trend=%s f&g=%s equity=%s",
             snap["price"]["last"], snap["price"]["trend"],
             snap["sentiment"]["fear_greed"], account.get("equity_usd"))

    mse = await classify_regime(snap)
    log.info("regime=%s (%s%%) layer1=%s", mse.get("regime"), mse.get("confidence_pct"), mse.get("pte_layer1_input"))

    pte = await analyze_trade(snap, mse)
    log.info("signal=%s conf=%s rr=%s", pte.get("signal"), pte.get("confidence_pct"), pte.get("rr"))

    decision = evaluate(pte, mse, snap)
    log.info("approved=%s | %s", decision["approved"], " | ".join(decision["reasons"]))

    if decision["approved"]:
        result = await ex.execute(decision)
        log.info("execute -> %s", result)
        await send(format_trade(decision, account, result))
    elif CONFIG.notify_every_cycle:
        await send(format_notrade(decision, account))


async def main():
    ex = Exchange()
    await ex.start()
    log.info("BOT START | dry_run=%s | model=%s | loop=%dmin | %s",
             CONFIG.dry_run, CONFIG.model, CONFIG.loop_minutes, CONFIG.lighter_base_url)
    await send(f"PTE Bot ONLINE - {'DRY-RUN' if CONFIG.dry_run else 'LIVE testnet'} - "
               f"loop tiap {CONFIG.loop_minutes} menit.")
    try:
        while True:
            try:
                await run_cycle(ex)
            except Exception as e:
                log.exception("cycle error")
                with contextlib.suppress(Exception):
                    await send(f"PTE Bot ERROR: {type(e).__name__}: {e}")
            await asyncio.sleep(CONFIG.loop_minutes * 60)
    finally:
        await ex.close()


if __name__ == "__main__":
    asyncio.run(main())
