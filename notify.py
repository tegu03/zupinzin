"""Telegram notifications: capital, PnL, capital + profit/loss, and the decision."""
import httpx
from config import CONFIG


async def send(text):
    if not CONFIG.telegram_token or not CONFIG.telegram_chat_id:
        print("[notify] telegram not configured; message:\n", text)
        return
    url = f"https://api.telegram.org/bot{CONFIG.telegram_token}/sendMessage"
    async with httpx.AsyncClient() as c:
        try:
            await c.post(url, json={"chat_id": CONFIG.telegram_chat_id, "text": text}, timeout=20)
        except Exception as e:
            print("[notify] send failed:", e)


def _f(x):
    try:
        return f"{float(x):,.2f}"
    except (TypeError, ValueError):
        return "n/a"


def _sgn(x):
    try:
        return ("+" if float(x) >= 0 else "") + _f(x)
    except (TypeError, ValueError):
        return "n/a"


def _header(account):
    a = account
    return (
        "PTE Bot - BTC Perp (Lighter Testnet)\n"
        f"Sumber data akun: {a.get('source', '?')}\n\n"
        "MODAL & PnL\n"
        f"- Total Modal (Equity): ${_f(a.get('equity_usd'))}\n"
        f"- Modal Awal: ${_f(a.get('base_capital_usd'))}\n"
        f"- PnL Belum Terealisasi: ${_sgn(a.get('unrealized_pnl_usd'))}\n"
        f"- PnL Hari Ini (mark-to-market): ${_sgn(a.get('realized_pnl_today_usd'))}\n"
        f"- Modal + P/L Hari Ini: {_sgn(a.get('daily_pnl_pct'))}%\n"
    )


def format_trade(decision, account, exec_result):
    d, e = decision, exec_result
    cfg = CONFIG
    if e.get("ok"):
        ex = "OK - tx " + str(e.get("tx_hash", "-"))
    else:
        ex = "GAGAL - " + str(e.get("error", "unknown"))
    warn = ("\n- PERINGATAN: " + e["warning"]) if e.get("warning") else ""
    return (
        _header(account) + "\n"
        f"ORDER {str(d['signal']).upper()} - Confidence {d.get('confidence_pct')}%\n"
        f"- Regime: {d.get('regime')}\n"
        f"- Entry: ${_f(d.get('entry'))} ({d.get('entry_type')})\n"
        f"- Invalidation (SL): ${_f(d.get('stop'))}\n"
        f"- Target: TP1 ${_f(d.get('tp1'))} | TP2 ${_f(d.get('tp2'))}\n"
        f"- R:R: {d.get('rr')}\n"
        f"- Size: ${_f(d.get('notional_usd'))} notional | {d.get('base_amount')} unit\n"
        f"- Risiko: ${_f(d.get('risk_usd'))} ({cfg.risk_pct * 100}%) | stop {d.get('stop_distance_pct')}%\n"
        f"- Mode: {'DRY-RUN (tidak kirim order nyata)' if d.get('dry_run') else 'LIVE (testnet)'}\n"
        f"- Eksekusi: {ex}{warn}\n\n"
        "Bukan nasihat finansial. Testnet dulu sampai expectancy terbukti."
    )


def format_notrade(decision, account):
    d = decision
    return (
        _header(account) + "\n"
        "NO-TRADE / VETO\n"
        f"- Sinyal AI: {d.get('signal')} (conf {d.get('confidence_pct')}%)\n"
        f"- Regime: {d.get('regime')}\n"
        f"- Alasan: {' | '.join(d.get('reasons', []))}\n"
        f"- Menunggu: {d.get('flip_if') or d.get('abstain_reason') or '-'}\n\n"
        "NO-TRADE beralasan = output berkualitas. Bukan nasihat finansial."
    )
