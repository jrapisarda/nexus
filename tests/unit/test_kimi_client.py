"""Unit tests for nexus_core.llm.client — KimiClient, KimiResponse, ShutdownRequestedError."""

import asyncio
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus_core.config import NexusSettings
from nexus_core.llm.client import (
    KimiClient,
    KimiResponse,
    MalformedModelResponseError,
    ShutdownRequestedError,
)
from nexus_core.utils.cost import BudgetExhaustedError, CostGuard


# ---------------------------------------------------------------------------
# KimiResponse dataclass
# ---------------------------------------------------------------------------

class TestKimiResponseDataclass:
    """Verify KimiResponse dataclass fields and construction."""

    def test_kimi_response_dataclass_fields(self):
        resp = KimiResponse(
            content="test content",
            reasoning="step-by-step reasoning",
            input_tokens=100,
            thinking_tokens=50,
            output_tokens=200,
            cost_usd=Decimal("0.05"),
            latency_ms=1500,
            model="kimi-k2.5",
            prompt_hash="abc123",
        )
        assert resp.content == "test content"
        assert resp.reasoning == "step-by-step reasoning"
        assert resp.input_tokens == 100
        assert resp.thinking_tokens == 50
        assert resp.output_tokens == 200
        assert resp.cost_usd == Decimal("0.05")
        assert resp.latency_ms == 1500
        assert resp.model == "kimi-k2.5"
        assert resp.prompt_hash == "abc123"

    def test_kimi_response_none_reasoning(self):
        resp = KimiResponse(
            content="content",
            reasoning=None,
            input_tokens=0,
            thinking_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
            latency_ms=0,
            model="kimi-k2.5",
            prompt_hash="hash",
        )
        assert resp.reasoning is None

    def test_kimi_response_equality(self):
        kwargs = dict(
            content="a", reasoning=None, input_tokens=1,
            thinking_tokens=0, output_tokens=1, cost_usd=Decimal("0.01"),
            latency_ms=10, model="m", prompt_hash="h",
        )
        assert KimiResponse(**kwargs) == KimiResponse(**kwargs)


# ---------------------------------------------------------------------------
# ShutdownRequestedError
# ---------------------------------------------------------------------------

class TestShutdownRequestedError:

    def test_is_exception(self):
        assert issubclass(ShutdownRequestedError, Exception)

    def test_message(self):
        err = ShutdownRequestedError("shutdown now")
        assert str(err) == "shutdown now"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def settings():
    return NexusSettings(
        MOONSHOT_API_KEY="test-key-abc",
        MOONSHOT_BASE_URL="https://test.api/v1",
        MOONSHOT_MODEL="kimi-k2.5",
        BUDGET_CEILING_USD=Decimal("100.00"),
    )


@pytest.fixture
def cost_guard(settings):
    return CostGuard.from_settings(settings)


def _build_mock_response(content="Hello", reasoning_content=None,
                         prompt_tokens=10, completion_tokens=20,
                         reasoning_tokens=0):
    """Build a mock OpenAI-style response object."""
    message = MagicMock()
    message.content = content
    message.reasoning_content = reasoning_content

    choice = MagicMock()
    choice.message = message

    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.reasoning_tokens = reasoning_tokens

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


# ---------------------------------------------------------------------------
# KimiClient.call_thinking
# ---------------------------------------------------------------------------

class TestCallThinking:

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_call_thinking_returns_kimi_response(self, MockAsyncOpenAI, settings, cost_guard):
        """A successful call_thinking should return a KimiResponse with correct fields."""
        mock_response = _build_mock_response(
            content="The answer is 42",
            reasoning_content="I thought carefully",
            prompt_tokens=50,
            completion_tokens=100,
            reasoning_tokens=30,
        )
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)

        result = await client.call_thinking(system="You are helpful", user="What is 6*7?")

        assert isinstance(result, KimiResponse)
        assert result.content == "The answer is 42"
        assert result.reasoning == "I thought carefully"
        assert result.input_tokens == 50
        assert result.output_tokens == 100
        assert result.thinking_tokens == 30
        assert result.model == "kimi-k2.5"
        assert isinstance(result.cost_usd, Decimal)
        assert result.cost_usd > 0
        assert result.latency_ms >= 0
        assert len(result.prompt_hash) == 64

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_call_thinking_raises_on_empty_final_content(self, MockAsyncOpenAI, settings, cost_guard):
        mock_response = _build_mock_response(
            content="",
            reasoning_content="Detailed reasoning but no final answer",
            prompt_tokens=50,
            completion_tokens=100,
            reasoning_tokens=30,
        )
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)

        with pytest.raises(MalformedModelResponseError, match="empty final content"):
            await client.call_thinking(system="You are helpful", user="What is 6*7?")

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_call_thinking_uses_temperature_1(self, MockAsyncOpenAI, settings, cost_guard):
        """call_thinking should use temperature=1.0 and thinking_enabled=True."""
        mock_response = _build_mock_response()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)
        await client.call_thinking(system="sys", user="usr")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 1.0
        # Thinking mode should NOT have extra_body with thinking disabled
        assert "extra_body" not in call_kwargs


# ---------------------------------------------------------------------------
# KimiClient.call_instant
# ---------------------------------------------------------------------------

class TestCallInstant:

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_call_instant_disables_thinking(self, MockAsyncOpenAI, settings, cost_guard):
        """call_instant should pass extra_body with thinking disabled."""
        mock_response = _build_mock_response()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)
        await client.call_instant(system="sys", user="usr")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
        assert call_kwargs["temperature"] == 0.6

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_call_instant_returns_kimi_response(self, MockAsyncOpenAI, settings, cost_guard):
        mock_response = _build_mock_response(content="Quick answer")
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)
        result = await client.call_instant(system="sys", user="usr")

        assert isinstance(result, KimiResponse)
        assert result.content == "Quick answer"


# ---------------------------------------------------------------------------
# Shutdown and budget protection
# ---------------------------------------------------------------------------

class TestShutdownProtection:

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_shutdown_event_raises(self, MockAsyncOpenAI, settings, cost_guard):
        """When shutdown_event is set, new calls should raise ShutdownRequestedError."""
        shutdown_event = asyncio.Event()
        shutdown_event.set()

        MockAsyncOpenAI.return_value = AsyncMock()
        client = KimiClient(settings, cost_guard, shutdown_event=shutdown_event)

        with pytest.raises(ShutdownRequestedError, match="Shutdown in progress"):
            await client.call_thinking(system="sys", user="usr")

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_shutdown_event_not_set_allows_call(self, MockAsyncOpenAI, settings, cost_guard):
        """When shutdown_event is NOT set, calls should proceed normally."""
        shutdown_event = asyncio.Event()
        # Not set

        mock_response = _build_mock_response()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard, shutdown_event=shutdown_event)
        result = await client.call_thinking(system="sys", user="usr")
        assert isinstance(result, KimiResponse)


class TestBudgetProtection:

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_budget_exhausted_raises(self, MockAsyncOpenAI, settings):
        """When cost_guard is near limit, new calls should raise BudgetExhaustedError."""
        guard = CostGuard(
            budget_ceiling_usd=Decimal("1.00"),
            cost_input_per_million=Decimal("0.60"),
            cost_output_per_million=Decimal("2.50"),
        )
        # Spend 99% of the budget
        guard.record_exact_cost(Decimal("0.99"))

        MockAsyncOpenAI.return_value = AsyncMock()
        client = KimiClient(settings, guard)

        with pytest.raises(BudgetExhaustedError):
            await client.call_thinking(system="sys", user="usr")


# ---------------------------------------------------------------------------
# KimiClient.close and properties
# ---------------------------------------------------------------------------

class TestClientLifecycle:

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_close_calls_underlying_client(self, MockAsyncOpenAI, settings, cost_guard):
        mock_client = AsyncMock()
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)
        await client.close()
        mock_client.close.assert_called_once()

    @patch("nexus_core.llm.client.AsyncOpenAI")
    def test_cost_guard_property(self, MockAsyncOpenAI, settings, cost_guard):
        MockAsyncOpenAI.return_value = AsyncMock()
        client = KimiClient(settings, cost_guard)
        assert client.cost_guard is cost_guard


# ---------------------------------------------------------------------------
# Prompt hash determinism
# ---------------------------------------------------------------------------

class TestPromptHash:

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_same_prompt_same_hash(self, MockAsyncOpenAI, settings, cost_guard):
        mock_response = _build_mock_response()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)

        result1 = await client.call_thinking(system="sys", user="usr")

        # Reset cost guard for second call
        guard2 = CostGuard.from_settings(settings)
        MockAsyncOpenAI.return_value = mock_client
        client2 = KimiClient(settings, guard2)
        result2 = await client2.call_thinking(system="sys", user="usr")

        assert result1.prompt_hash == result2.prompt_hash

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_different_prompt_different_hash(self, MockAsyncOpenAI, settings, cost_guard):
        mock_response = _build_mock_response()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)

        result1 = await client.call_thinking(system="sys1", user="usr1")
        result2 = await client.call_thinking(system="sys2", user="usr2")

        assert result1.prompt_hash != result2.prompt_hash


# ---------------------------------------------------------------------------
# Tools parameter
# ---------------------------------------------------------------------------

class TestToolsParameter:

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_tools_passed_to_api(self, MockAsyncOpenAI, settings, cost_guard):
        mock_response = _build_mock_response()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)
        tools = [{"type": "function", "function": {"name": "search"}}]
        await client.call_thinking(system="sys", user="usr", tools=tools)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["tools"] == tools

    @patch("nexus_core.llm.client.AsyncOpenAI")
    async def test_no_tools_omits_key(self, MockAsyncOpenAI, settings, cost_guard):
        mock_response = _build_mock_response()
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        MockAsyncOpenAI.return_value = mock_client

        client = KimiClient(settings, cost_guard)
        await client.call_thinking(system="sys", user="usr", tools=None)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert "tools" not in call_kwargs


# ---------------------------------------------------------------------------
# _build_user_content — multimodal support (Phase 2-7)
# ---------------------------------------------------------------------------

class TestBuildUserContent:
    """Verify _build_user_content() builds the correct user content structure."""

    def test_no_images_returns_plain_string(self):
        """With no images, returns the user text as a plain string."""
        result = KimiClient._build_user_content("Hello world", None)

        assert result == "Hello world"
        assert isinstance(result, str)

    def test_empty_image_list_returns_plain_string(self):
        """An empty image list is treated the same as None."""
        result = KimiClient._build_user_content("Hello world", [])

        assert result == "Hello world"
        assert isinstance(result, str)

    def test_with_images_returns_list_with_text_and_image_parts(self, tmp_path):
        """With valid images, returns a list containing text and image_url parts."""
        # Create a minimal valid PNG file (1x1 pixel)
        img_path = tmp_path / "test.png"
        # Minimal 1x1 white PNG
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
            b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01'
            b'\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        img_path.write_bytes(png_bytes)

        result = KimiClient._build_user_content("Analyze this image", [img_path])

        assert isinstance(result, list)
        assert len(result) == 2

        # First part is text
        assert result[0]["type"] == "text"
        assert result[0]["text"] == "Analyze this image"

        # Second part is image_url
        assert result[1]["type"] == "image_url"
        assert result[1]["image_url"]["url"].startswith("data:image/png;base64,")

    def test_with_multiple_images(self, tmp_path):
        """Multiple images produce multiple image_url parts."""
        img1 = tmp_path / "a.png"
        img2 = tmp_path / "b.jpg"
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
            b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01'
            b'\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        img1.write_bytes(png_bytes)
        img2.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 20)  # minimal JPEG header

        result = KimiClient._build_user_content("Analyze images", [img1, img2])

        assert isinstance(result, list)
        assert len(result) == 3  # text + 2 images
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image_url"
        assert result[2]["type"] == "image_url"

    def test_jpg_uses_jpeg_mime_type(self, tmp_path):
        """A .jpg file gets the 'image/jpeg' MIME type, not 'image/jpg'."""
        img_path = tmp_path / "photo.jpg"
        img_path.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 20)

        result = KimiClient._build_user_content("Describe", [img_path])

        assert isinstance(result, list)
        assert "image/jpeg" in result[1]["image_url"]["url"]

    def test_png_uses_png_mime_type(self, tmp_path):
        """A .png file gets the 'image/png' MIME type."""
        img_path = tmp_path / "chart.png"
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
            b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01'
            b'\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        img_path.write_bytes(png_bytes)

        result = KimiClient._build_user_content("Describe", [img_path])

        assert isinstance(result, list)
        assert "image/png" in result[1]["image_url"]["url"]

    def test_nonexistent_image_path_is_skipped(self, tmp_path):
        """A non-existent image path is silently skipped."""
        missing = tmp_path / "nonexistent.png"

        result = KimiClient._build_user_content("Analyze", [missing])

        # Since the only image was skipped and parts has only the text element,
        # the method returns the plain string
        assert result == "Analyze"
        assert isinstance(result, str)

    def test_mix_of_existing_and_nonexistent(self, tmp_path):
        """Only existing images are included; missing ones are skipped."""
        real_img = tmp_path / "real.png"
        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01'
            b'\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde'
            b'\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01'
            b'\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82'
        )
        real_img.write_bytes(png_bytes)
        missing = tmp_path / "missing.png"

        result = KimiClient._build_user_content("Analyze", [real_img, missing])

        assert isinstance(result, list)
        assert len(result) == 2  # text + 1 real image
        assert result[0]["type"] == "text"
        assert result[1]["type"] == "image_url"

    def test_all_nonexistent_images_returns_plain_string(self, tmp_path):
        """If all image paths are non-existent, falls back to plain string."""
        missing1 = tmp_path / "gone1.png"
        missing2 = tmp_path / "gone2.png"

        result = KimiClient._build_user_content("Text only", [missing1, missing2])

        assert result == "Text only"
        assert isinstance(result, str)

    def test_webp_uses_webp_mime_type(self, tmp_path):
        """A .webp file gets the 'image/webp' MIME type."""
        img_path = tmp_path / "image.webp"
        img_path.write_bytes(b'RIFF' + b'\x00' * 20 + b'WEBP')

        result = KimiClient._build_user_content("Describe", [img_path])

        assert isinstance(result, list)
        assert "image/webp" in result[1]["image_url"]["url"]
