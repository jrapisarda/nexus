"""Unit tests for nexus_core.config — NexusSettings and get_settings()."""

from decimal import Decimal

import pytest

from nexus_core.config import NexusSettings, get_settings


class TestNexusSettingsDefaults:
    """Verify that NexusSettings provides the correct defaults."""

    def test_default_database_url(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.DATABASE_URL == "postgresql+asyncpg://claudeai:Magic123@localhost:5432/nexus"

    def test_default_moonshot_model(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MOONSHOT_MODEL == "kimi-k2.5"

    def test_default_moonshot_base_url(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MOONSHOT_BASE_URL == "https://api.moonshot.cn/v1"

    def test_default_budget_ceiling_usd(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.BUDGET_CEILING_USD == Decimal("38.25")

    def test_default_cost_input_per_million(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.COST_INPUT_PER_MILLION == Decimal("0.60")

    def test_default_cost_output_per_million(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.COST_OUTPUT_PER_MILLION == Decimal("2.50")

    def test_default_max_concurrent_calls(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MAX_CONCURRENT_CALLS == 3

    def test_default_rent_decay_rate(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.RENT_DECAY_RATE == Decimal("0.05")

    def test_default_rent_decay_interval_mins(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.RENT_DECAY_INTERVAL_MINS == 60

    def test_default_survival_threshold(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.SURVIVAL_THRESHOLD == Decimal("10.00")

    def test_default_min_personas_per_role_class(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MIN_PERSONAS_PER_ROLE_CLASS == 2

    def test_default_max_active_personas(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MAX_ACTIVE_PERSONAS == 20

    def test_default_mutation_max_edit_distance_pct(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MUTATION_MAX_EDIT_DISTANCE_PCT == pytest.approx(0.30)

    def test_default_diversity_threshold(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.DIVERSITY_THRESHOLD == pytest.approx(0.35)

    def test_default_confidence_decay_per_hop(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.CONFIDENCE_DECAY_PER_HOP == pytest.approx(0.7)

    def test_default_dedup_similarity_threshold(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.DEDUP_SIMILARITY_THRESHOLD == pytest.approx(0.92)

    def test_default_max_dag_depth(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MAX_DAG_DEPTH == 6

    def test_default_max_dag_fanout(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MAX_DAG_FANOUT == 8

    def test_default_circuit_breaker_fail_max(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.CIRCUIT_BREAKER_FAIL_MAX == 2

    def test_default_circuit_breaker_reset_timeout_secs(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.CIRCUIT_BREAKER_RESET_TIMEOUT_SECS == 300

    def test_default_review_variance_threshold(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.REVIEW_VARIANCE_THRESHOLD == pytest.approx(1.5)

    def test_default_embedding_model(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.EMBEDDING_MODEL == "all-MiniLM-L6-v2"

    def test_default_embedding_dim(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.EMBEDDING_DIM == 384

    def test_default_log_level(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.LOG_LEVEL == "INFO"

    def test_default_log_format(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.LOG_FORMAT == "console"

    def test_default_dream_cycle_inactivity_secs(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.DREAM_CYCLE_INACTIVITY_SECS == 300

    # ── File Upload settings (Phase 0/1) ──────────────────────────────────

    def test_default_uploads_dir(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.UPLOADS_DIR == "./uploads"

    def test_default_max_file_size_bytes(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.MAX_FILE_SIZE_BYTES == 20_971_520  # 20MB

    def test_default_file_context_budget_chars(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.FILE_CONTEXT_BUDGET_CHARS == 512_000

    def test_default_file_context_max_files(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.FILE_CONTEXT_MAX_FILES == 5

    def test_default_nexus_api_url(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert s.NEXUS_API_URL == "http://localhost:8000"


class TestNexusSettingsCustomValues:
    """Verify that custom values override defaults."""

    def test_custom_values(self):
        s = NexusSettings(
            DATABASE_URL="postgresql+asyncpg://user:pass@db:5432/custom",
            MOONSHOT_API_KEY="my-secret-key",
            MOONSHOT_MODEL="custom-model",
            BUDGET_CEILING_USD=Decimal("100.00"),
            MAX_CONCURRENT_CALLS=10,
            LOG_LEVEL="DEBUG",
            LOG_FORMAT="json",
        )
        assert s.DATABASE_URL == "postgresql+asyncpg://user:pass@db:5432/custom"
        assert s.MOONSHOT_API_KEY == "my-secret-key"
        assert s.MOONSHOT_MODEL == "custom-model"
        assert s.BUDGET_CEILING_USD == Decimal("100.00")
        assert s.MAX_CONCURRENT_CALLS == 10
        assert s.LOG_LEVEL == "DEBUG"
        assert s.LOG_FORMAT == "json"

    def test_custom_economy_settings(self):
        s = NexusSettings(
            MOONSHOT_API_KEY="k",
            RENT_DECAY_RATE=Decimal("0.10"),
            RENT_DECAY_INTERVAL_MINS=30,
            SURVIVAL_THRESHOLD=Decimal("20.00"),
            MIN_PERSONAS_PER_ROLE_CLASS=5,
        )
        assert s.RENT_DECAY_RATE == Decimal("0.10")
        assert s.RENT_DECAY_INTERVAL_MINS == 30
        assert s.SURVIVAL_THRESHOLD == Decimal("20.00")
        assert s.MIN_PERSONAS_PER_ROLE_CLASS == 5

    def test_custom_evolution_settings(self):
        s = NexusSettings(
            MOONSHOT_API_KEY="k",
            MAX_ACTIVE_PERSONAS=50,
            MUTATION_MAX_EDIT_DISTANCE_PCT=0.50,
            DIVERSITY_THRESHOLD=0.80,
        )
        assert s.MAX_ACTIVE_PERSONAS == 50
        assert s.MUTATION_MAX_EDIT_DISTANCE_PCT == pytest.approx(0.50)
        assert s.DIVERSITY_THRESHOLD == pytest.approx(0.80)

    def test_custom_file_upload_settings(self):
        s = NexusSettings(
            MOONSHOT_API_KEY="k",
            UPLOADS_DIR="/data/uploads",
            MAX_FILE_SIZE_BYTES=10_485_760,
            FILE_CONTEXT_BUDGET_CHARS=256_000,
            FILE_CONTEXT_MAX_FILES=10,
            NEXUS_API_URL="http://api.nexus.local:9000",
        )
        assert s.UPLOADS_DIR == "/data/uploads"
        assert s.MAX_FILE_SIZE_BYTES == 10_485_760
        assert s.FILE_CONTEXT_BUDGET_CHARS == 256_000
        assert s.FILE_CONTEXT_MAX_FILES == 10
        assert s.NEXUS_API_URL == "http://api.nexus.local:9000"

    def test_ignores_unrelated_env_values(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("MOONSHOT_API_KEY=k\nPOSTGRES_PORT=5433\n", encoding="utf-8")

        s = NexusSettings(_env_file=env_file)

        assert s.MOONSHOT_API_KEY == "k"


class TestNexusSettingsDecimalFields:
    """Verify that Decimal fields are actually Decimal instances, not floats."""

    def test_budget_ceiling_usd_is_decimal(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert isinstance(s.BUDGET_CEILING_USD, Decimal)

    def test_cost_input_per_million_is_decimal(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert isinstance(s.COST_INPUT_PER_MILLION, Decimal)

    def test_cost_output_per_million_is_decimal(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert isinstance(s.COST_OUTPUT_PER_MILLION, Decimal)

    def test_rent_decay_rate_is_decimal(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert isinstance(s.RENT_DECAY_RATE, Decimal)

    def test_survival_threshold_is_decimal(self):
        s = NexusSettings(MOONSHOT_API_KEY="k")
        assert isinstance(s.SURVIVAL_THRESHOLD, Decimal)


class TestGetSettingsSingleton:
    """Verify that get_settings() returns a cached singleton."""

    def test_get_settings_returns_nexus_settings(self):
        # Clear the cache so we get a fresh instance for this test
        get_settings.cache_clear()
        result = get_settings()
        assert isinstance(result, NexusSettings)

    def test_get_settings_singleton(self):
        """Calling get_settings() twice should return the same object."""
        get_settings.cache_clear()
        first = get_settings()
        second = get_settings()
        assert first is second

    def test_get_settings_cache_clear_gives_new_instance(self):
        """After cache_clear(), get_settings() should return a new instance."""
        get_settings.cache_clear()
        first = get_settings()
        get_settings.cache_clear()
        second = get_settings()
        # They are equal in value but are distinct objects
        assert first is not second
