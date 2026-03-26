import asyncio
import base64
import hashlib
import json
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import httpx
import structlog

from nexus_core.config import NexusSettings
from nexus_core.utils.cost import CostGuard, BudgetExhaustedError

logger = structlog.get_logger(__name__)

@dataclass
class KimiResponse:
    """Response from a Kimi K2.5 API call."""
    content: str
    reasoning: Optional[str]
    input_tokens: int
    thinking_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    model: str
    prompt_hash: str


class ShutdownRequestedError(Exception):
    """Raised when a shutdown is in progress and new calls are rejected."""
    pass


class MalformedModelResponseError(Exception):
    """Raised when the model returns an empty or unusable final answer."""
    pass


class KimiClient:
    """Async client for Kimi K2.5 API with budget protection and concurrency control."""

    def __init__(
        self,
        settings: NexusSettings,
        cost_guard: CostGuard,
        semaphore: asyncio.Semaphore | None = None,
        shutdown_event: asyncio.Event | None = None,
    ):
        self._settings = settings
        self._cost_guard = cost_guard
        self._semaphore = semaphore or asyncio.Semaphore(settings.MAX_CONCURRENT_CALLS)
        self._shutdown_event = shutdown_event or asyncio.Event()
        self._client = AsyncOpenAI(
            api_key=settings.MOONSHOT_API_KEY,
            base_url=settings.MOONSHOT_BASE_URL,
        )

    async def call_thinking(
        self,
        system: str,
        user: str,
        tools: list[dict] | None = None,
        max_tokens: int = 8192,
    ) -> KimiResponse:
        """Call Kimi K2.5 in thinking mode (deep reasoning)."""
        return await self._call(
            system=system,
            user=user,
            tools=tools,
            max_tokens=max_tokens,
            temperature=1.0,
            top_p=0.95,
            thinking_enabled=True,
        )

    async def call_instant(
        self,
        system: str,
        user: str,
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
    ) -> KimiResponse:
        """Call Kimi K2.5 in instant mode (fast, cheaper)."""
        return await self._call(
            system=system,
            user=user,
            tools=tools,
            max_tokens=max_tokens,
            temperature=0.6,
            top_p=0.95,
            thinking_enabled=False,
        )

    async def call_multimodal(
        self,
        system: str,
        user_text: str,
        image_paths: list[Path] | None = None,
        max_tokens: int = 8192,
    ) -> KimiResponse:
        """Call Kimi K2.5 with multimodal content (text + images).

        Images are base64-encoded inline per the Moonshot API spec.
        Falls back to standard text call if no images provided.
        """
        user_content = self._build_user_content(user_text, image_paths)
        return await self._call(
            system=system,
            user=user_text,
            tools=None,
            max_tokens=max_tokens,
            temperature=1.0,
            top_p=0.95,
            thinking_enabled=True,
            user_content=user_content,
        )

    @staticmethod
    def _build_user_content(
        user_text: str,
        image_paths: list[Path] | None,
    ) -> str | list[dict]:
        """Build the user content for the messages array.

        Returns a plain string if no images, or a list of content parts
        (text + image_url items) for multimodal requests.
        """
        if not image_paths:
            return user_text

        parts: list[dict] = [{"type": "text", "text": user_text}]

        for path in image_paths:
            if not path.exists():
                continue
            b64_data = base64.b64encode(path.read_bytes()).decode()
            suffix = path.suffix.lstrip(".").lower()
            mime = f"image/{suffix}" if suffix != "jpg" else "image/jpeg"
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64_data}"},
            })

        return parts if len(parts) > 1 else user_text

    async def _call(
        self,
        system: str,
        user: str,
        tools: list[dict] | None,
        max_tokens: int,
        temperature: float,
        top_p: float,
        thinking_enabled: bool,
        user_content: str | list[dict] | None = None,
    ) -> KimiResponse:
        """Internal method to make an API call with budget check, semaphore, and retry."""
        # Check shutdown
        if self._shutdown_event.is_set():
            raise ShutdownRequestedError("Shutdown in progress, rejecting new API call")

        # Estimate and check budget BEFORE acquiring semaphore
        prompt_text = system + user
        estimated_input_tokens = len(prompt_text) // 4  # rough estimate
        self._cost_guard.check_budget(estimated_input_tokens, max_tokens)

        # Build messages — use user_content if provided (multimodal), else plain string
        effective_user_content = user_content if user_content is not None else user
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": effective_user_content},
        ]

        # Compute prompt hash for telemetry dedup
        if isinstance(effective_user_content, list):
            hash_input = system + json.dumps(effective_user_content, sort_keys=True)
        else:
            hash_input = prompt_text
        prompt_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:64]

        # Build kwargs
        kwargs = {
            "model": self._settings.MOONSHOT_MODEL,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
        }

        if tools:
            kwargs["tools"] = tools

        if not thinking_enabled:
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        # Acquire semaphore and make the call
        async with self._semaphore:
            start_time = time.monotonic()
            response = await self._make_api_call(**kwargs)
            latency_ms = int((time.monotonic() - start_time) * 1000)

        # Parse response
        choice = response.choices[0]
        content = choice.message.content or ""
        reasoning = getattr(choice.message, 'reasoning_content', None)

        if not content.strip():
            raise MalformedModelResponseError(
                "Model returned empty final content"
            )

        # Extract token usage
        usage = response.usage
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        # thinking tokens may be in a separate field or included in completion
        thinking_tokens = getattr(usage, 'reasoning_tokens', 0) or 0

        # Record actual cost
        cost = self._cost_guard.record_spend(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
        )

        return KimiResponse(
            content=content,
            reasoning=reasoning,
            input_tokens=input_tokens,
            thinking_tokens=thinking_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            model=self._settings.MOONSHOT_MODEL,
            prompt_hash=prompt_hash,
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.TimeoutException)),
        reraise=True,
    )
    async def _make_api_call(self, **kwargs):
        """Make the actual API call with retry logic."""
        try:
            return await asyncio.wait_for(
                self._client.chat.completions.create(**kwargs),
                timeout=300.0,  # 5 minute timeout for thinking mode
            )
        except asyncio.TimeoutError:
            raise httpx.TimeoutException("Kimi K2.5 API call timed out after 300s")

    @property
    def cost_guard(self) -> CostGuard:
        return self._cost_guard

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.close()
