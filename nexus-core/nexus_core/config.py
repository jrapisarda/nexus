"""NEXUS configuration via Pydantic Settings."""

from decimal import Decimal
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class NexusSettings(BaseSettings):
    """Central configuration for the NEXUS platform."""

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://claudeai:Magic123@localhost:5432/nexus"

    # Moonshot AI
    MOONSHOT_API_KEY: str = ""
    MOONSHOT_BASE_URL: str = "https://api.moonshot.cn/v1"
    MOONSHOT_MODEL: str = "kimi-k2.5"

    # Budget
    BUDGET_CEILING_USD: Decimal = Decimal("38.25")
    COST_INPUT_PER_MILLION: Decimal = Decimal("0.60")
    COST_OUTPUT_PER_MILLION: Decimal = Decimal("2.50")

    # Concurrency
    MAX_CONCURRENT_CALLS: int = 3
    STALE_INSTANCE_TIMEOUT_SECS: int = 900

    # Economy
    RENT_DECAY_RATE: Decimal = Decimal("0.05")
    RENT_DECAY_INTERVAL_MINS: int = 60
    SURVIVAL_THRESHOLD: Decimal = Decimal("10.00")
    MIN_PERSONAS_PER_ROLE_CLASS: int = 2
    MARKET_LOOP_INTERVAL_SECS: int = 20
    MARKET_IDLE_BALANCE_THRESHOLD: Decimal = Decimal("120.00")
    MARKET_ACTION_COST_USD: Decimal = Decimal("0.000500")
    MARKET_SERVICE_TIMEOUT_MINS: int = 30
    MARKET_MAX_LISTINGS_PER_PERSONA: int = 2
    MARKET_MAX_OPEN_ORDERS_PER_PERSONA: int = 6
    MARKET_DEFAULT_COLLATERAL_RATIO: Decimal = Decimal("1.50")

    # Salary
    SALARY_BUDGET_RATE: Decimal = Decimal("0.12")
    SALARY_MIN_CREDITS: Decimal = Decimal("1.00")
    SALARY_MAX_CREDITS: Decimal = Decimal("5.00")

    # Progressive Rent & Welfare
    RENT_DECAY_RATE_LOW: Decimal = Decimal("0.03")
    RENT_DECAY_RATE_MID: Decimal = Decimal("0.05")
    RENT_DECAY_RATE_HIGH: Decimal = Decimal("0.08")
    RENT_DECAY_EXEMPT_BELOW: Decimal = Decimal("20.00")
    RENT_DECAY_HIGH_ABOVE: Decimal = Decimal("300.00")
    RENT_WELFARE_REDIRECT_RATIO: Decimal = Decimal("0.50")
    WELFARE_FLOOR_CREDITS: Decimal = Decimal("30.00")
    WELFARE_INTERVAL_TICKS: int = 2

    # Price Discovery
    MARKET_OBI_SENSITIVITY: float = 1.0

    # Node Ownership
    NODE_BASE_PRICE: Decimal = Decimal("5.00")
    NODE_EDGE_VALUE_MULTIPLIER: Decimal = Decimal("10.00")
    NODE_CENTRALITY_MULTIPLIER: Decimal = Decimal("50.00")
    NODE_MIN_PRICE: Decimal = Decimal("5.00")
    NODE_MAX_PRICE: Decimal = Decimal("500.00")
    NODE_MAX_OWNED_PER_AGENT: int = 5
    NODE_MAX_PORTFOLIO_PCT: Decimal = Decimal("0.15")
    NODE_CAPABILITY_GATE: Decimal = Decimal("0.50")
    NODE_YIELD_FROM_BOUNTY_PCT: Decimal = Decimal("0.05")
    NODE_DEPRECIATION_RATE: Decimal = Decimal("0.01")
    NODE_NEGLECT_THRESHOLD_CYCLES: int = 5
    NODE_TAKEOVER_NEGLECT_CYCLES: int = 10
    NODE_SUPERLINEAR_FACTOR: Decimal = Decimal("0.20")
    NODE_PURCHASE_MIN_BALANCE: Decimal = Decimal("30.00")
    NODE_PURCHASE_MAX_SPEND_PCT: Decimal = Decimal("0.40")
    NODE_PURCHASE_MIN_CONFIDENCE: Decimal = Decimal("0.30")

    # Wealth Tax
    WEALTH_TAX_TOP_RATE: Decimal = Decimal("0.015")
    WEALTH_TAX_MID_RATE: Decimal = Decimal("0.005")
    WEALTH_TAX_INTERVAL_TICKS: int = 4

    # Citation Verification
    CITATION_CHECK_TIMEOUT_SECS: int = 5
    CITATION_CACHE_TTL_DAYS: int = 30
    CITATION_CONCURRENT_LIMIT: int = 5

    # Evolution
    MAX_ACTIVE_PERSONAS: int = 20
    MUTATION_MAX_EDIT_DISTANCE_PCT: float = 0.30
    DIVERSITY_THRESHOLD: float = 0.35

    # Knowledge Graph
    CONFIDENCE_DECAY_PER_HOP: float = 0.7
    DEDUP_SIMILARITY_THRESHOLD: float = 0.92
    MAX_DAG_DEPTH: int = 6
    MAX_DAG_FANOUT: int = 8

    # Review
    CIRCUIT_BREAKER_FAIL_MAX: int = 2
    CIRCUIT_BREAKER_RESET_TIMEOUT_SECS: int = 300
    REVIEW_VARIANCE_THRESHOLD: float = 1.5
    RED_TEAM_SAMPLE_RATE: float = 0.1

    # Embeddings
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    # File Uploads
    UPLOADS_DIR: str = "./uploads"
    MAX_FILE_SIZE_BYTES: int = 20_971_520  # 20MB
    FILE_CONTEXT_BUDGET_CHARS: int = 512_000  # ~128K tokens at 4 chars/token
    FILE_CONTEXT_MAX_FILES: int = 5
    NEXUS_API_URL: str = "http://localhost:8000"

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "console"  # "console" or "json"
    REPORTS_DIR: str = "reports"

    # Scout APIs
    PUBMED_API_KEY: str = ""
    USPTO_API_KEY: str = ""
    SCOUT_RELEVANCE_THRESHOLD: float = 0.18
    SCOUT_SWEEP_INTERVAL_TICKS: int = 5

    # Dream Cycle
    DREAM_CYCLE_INACTIVITY_SECS: int = 300
    GOVERNANCE_INTERVAL_TICKS: int = 1
    EVOLUTION_INTERVAL_TICKS: int = 4
    INFILTRATION_INTERVAL_TICKS: int = 6

    model_config = SettingsConfigDict(extra="ignore")


@lru_cache(maxsize=1)
def get_settings() -> NexusSettings:
    """Singleton settings loader backed by the project .env file."""
    return NexusSettings(_env_file=".env", _env_file_encoding="utf-8")
