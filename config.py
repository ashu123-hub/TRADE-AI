"""
TradeMind AI - Central Configuration Module
Loads environment variables and exposes typed, validated settings.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# ─── Load .env ──────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ─── Logging ────────────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── API Keys ────────────────────────────────────────────────────────────────
class APIKeys:
    """Centralised, read-only API key access."""

    @staticmethod
    def _get(key: str, required: bool = False) -> str | None:
        value = os.getenv(key)
        if required and not value:
            logger.error("Required environment variable '%s' is not set.", key)
        return value

    @property
    def supabase_url(self) -> str | None:
        return self._get("SUPABASE_URL")

    @property
    def supabase_anon_key(self) -> str | None:
        return self._get("SUPABASE_ANON_KEY")

    @property
    def supabase_service_role_key(self) -> str | None:
        return self._get("SUPABASE_SERVICE_ROLE_KEY")

    @property
    def finnhub(self) -> str | None:
        return self._get("FINNHUB_API_KEY")

    @property
    def alpha_vantage(self) -> str | None:
        return self._get("ALPHA_VANTAGE_API_KEY")

    @property
    def gemini(self) -> str | None:
        return self._get("GEMINI_API_KEY")

    @property
    def yahoo_finance_enabled(self) -> bool:
        return os.getenv("YAHOO_FINANCE_ENABLED", "true").lower() in ("true", "1", "yes")

    @property
    def yahoo_finance_api_key(self) -> str | None:
        return self._get("YAHOO_FINANCE_API_KEY") or self._get("YAHOO_API_KEY") or self._get("RAPIDAPI_KEY")





# ─── Application Settings ────────────────────────────────────────────────────
class AppSettings:
    APP_NAME = "TradeMind AI"
    APP_VERSION = "1.0.0"
    APP_ENV = os.getenv("APP_ENV", "development")
    CACHE_TTL: int = int(os.getenv("CACHE_TTL_SECONDS", "300"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY: float = float(os.getenv("RETRY_DELAY_SECONDS", "2"))

    # Paths
    BASE_DIR: Path = BASE_DIR
    DATASET_DIR: Path = BASE_DIR / "dataset"
    MODELS_DIR: Path = BASE_DIR / "trained_models"

    # NSE
    NSE_EXCHANGE_SUFFIX = ".NS"
    BSE_EXCHANGE_SUFFIX = ".BO"
    DEFAULT_EXCHANGE = "NSE"

    # Market hours (IST = UTC+5:30)
    MARKET_OPEN_HOUR_IST = 9
    MARKET_OPEN_MIN_IST = 15
    MARKET_CLOSE_HOUR_IST = 15
    MARKET_CLOSE_MIN_IST = 30

    # Prediction defaults
    INTRADAY_INTERVALS = ["5m", "15m"]
    PREDICTION_LOOKBACK_DAYS = 365
    MIN_DATA_ROWS = 100

    # Risk management defaults
    DEFAULT_MAX_RISK_PER_TRADE_PCT = 2.0
    DEFAULT_DAILY_LOSS_LIMIT_PCT = 5.0


# ─── Singleton instances ─────────────────────────────────────────────────────
api_keys = APIKeys()
settings = AppSettings()

# Ensure required directories exist
for _dir in [settings.DATASET_DIR, settings.MODELS_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

logger.info("TradeMind AI config loaded (env=%s)", settings.APP_ENV)
