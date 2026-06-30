"""Central config. Reads everything from environment (.env)."""
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _f(k, d): return float(os.getenv(k, d))
def _i(k, d): return int(os.getenv(k, d))
def _b(k, d): return os.getenv(k, d).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    # --- DeepSeek (AI) ---
    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    thinking: bool = _b("DEEPSEEK_THINKING", "true")

    # --- Lighter (execution + account) ---
    lighter_base_url: str = os.getenv("LIGHTER_BASE_URL", "https://testnet.zklighter.elliot.ai")
    lighter_private_key: str = os.getenv("LIGHTER_PRIVATE_KEY", "")
    lighter_api_key_index: int = _i("LIGHTER_API_KEY_INDEX", "2")
    lighter_account_index: int = _i("LIGHTER_ACCOUNT_INDEX", "0")
    market_index: int = _i("LIGHTER_MARKET_INDEX", "1")
    price_decimals: int = _i("LIGHTER_PRICE_DECIMALS", "2")
    size_decimals: int = _i("LIGHTER_SIZE_DECIMALS", "5")
    initial_capital: float = _f("INITIAL_CAPITAL", "1000")
    mkt_slippage: float = _f("MKT_SLIPPAGE", "0.005")
    place_sl_tp: bool = _b("PLACE_SL_TP", "true")

    # --- Telegram ---
    telegram_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # --- Trading / engine ---
    binance_symbol: str = os.getenv("BINANCE_SYMBOL", "BTCUSDT")
    interval: str = os.getenv("INTERVAL", "1h")
    risk_pct: float = _f("RISK_PCT", "0.01")
    max_leverage: float = _f("MAX_LEVERAGE", "10")
    min_rr: float = _f("MIN_RR", "1.5")
    daily_loss_limit_pct: float = _f("DAILY_LOSS_LIMIT_PCT", "0.03")
    dry_run: bool = _b("DRY_RUN", "true")
    loop_minutes: int = _i("LOOP_MINUTES", "60")
    notify_every_cycle: bool = _b("NOTIFY_EVERY_CYCLE", "true")
    state_file: str = os.getenv("STATE_FILE", "bot_state.json")


CONFIG = Config()
