"""File context utilities for research context file uploads."""

from __future__ import annotations

import asyncio
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import sqlalchemy as sa
import structlog

logger = structlog.get_logger(__name__)

ALLOWED_EXTENSIONS: set[str] = {
    "pdf", "csv", "tsv", "txt", "json", "xlsx", "xls",
    "docx", "png", "jpg", "jpeg", "webp", "gif", "md",
}

IMAGE_EXTENSIONS: set[str] = {"png", "jpg", "jpeg", "webp", "gif"}

EXTRACTABLE_EXTENSIONS: set[str] = {"pdf", "docx", "xlsx", "xls", "pptx"}

DIRECT_READ_EXTENSIONS: set[str] = {"csv", "tsv", "txt", "json", "md"}


def validate_extension(filename: str) -> bool:
    """Check whether a filename has an allowed extension."""
    ext = Path(filename).suffix.lstrip(".").lower()
    return ext in ALLOWED_EXTENSIONS


def get_extension(filename: str) -> str:
    """Return the lowercase extension without the leading dot."""
    return Path(filename).suffix.lstrip(".").lower()


def is_image(filename: str) -> bool:
    """Return True if the file is an image type."""
    return get_extension(filename) in IMAGE_EXTENSIONS


def is_extractable(filename: str) -> bool:
    """Return True if the file should be sent to Moonshot for extraction."""
    return get_extension(filename) in EXTRACTABLE_EXTENSIONS


def is_direct_read(filename: str) -> bool:
    """Return True if the file can be read directly as text."""
    return get_extension(filename) in DIRECT_READ_EXTENSIONS


def sanitize_filename(name: str) -> str:
    """Sanitize a user-supplied filename for safe disk storage.

    - Strips path separators and directory traversal
    - Normalises Unicode
    - Limits length to 200 characters
    - Falls back to 'unnamed' if nothing remains
    """
    # Normalise unicode
    name = unicodedata.normalize("NFKD", name)
    # Strip any directory components
    name = Path(name).name
    # Remove anything that isn't alphanumeric, dash, underscore, or dot
    name = re.sub(r"[^\w.\-]", "_", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name).strip("_")
    # Limit length
    if len(name) > 200:
        stem = Path(name).stem[:190]
        suffix = Path(name).suffix[:10]
        name = stem + suffix
    return name or "unnamed"


@dataclass
class AttachmentContext:
    """Represents a loaded attachment ready for prompt injection."""
    attachment_id: UUID
    filename: str
    content_type: str
    size_bytes: int
    text_content: str | None = None
    image_path: Path | None = None


@dataclass
class FileContextBudget:
    """Enforces token budget on file context injection."""

    @staticmethod
    def check_and_truncate(
        contexts: list[AttachmentContext],
        budget_chars: int,
    ) -> list[AttachmentContext]:
        """Truncate or drop file contexts to fit within the character budget.

        Strategy:
        1. If total text fits within budget, return unchanged.
        2. Otherwise, truncate the largest text-bearing files first.
        3. If a single file still exceeds budget after others are dropped,
           truncate it with a [TRUNCATED] suffix.
        """
        text_contexts = [c for c in contexts if c.text_content]
        image_contexts = [c for c in contexts if c.image_path and not c.text_content]

        total_chars = sum(len(c.text_content) for c in text_contexts)
        if total_chars <= budget_chars:
            return contexts  # all fits

        logger.warning(
            "file_context_over_budget",
            total_chars=total_chars,
            budget_chars=budget_chars,
            file_count=len(text_contexts),
        )

        # Sort largest first for truncation priority
        text_contexts.sort(key=lambda c: len(c.text_content or ""), reverse=True)

        result: list[AttachmentContext] = []
        remaining = budget_chars

        # Process smallest first (reverse) to preserve as many files as possible
        for ctx in reversed(text_contexts):
            text_len = len(ctx.text_content or "")
            if text_len <= remaining:
                result.append(ctx)
                remaining -= text_len
            elif remaining > 500:
                # Truncate this file to fit
                truncated = AttachmentContext(
                    attachment_id=ctx.attachment_id,
                    filename=ctx.filename,
                    content_type=ctx.content_type,
                    size_bytes=ctx.size_bytes,
                    text_content=ctx.text_content[:remaining - 100]
                    + f"\n\n[TRUNCATED: original {text_len} chars, showing first {remaining - 100} chars]",
                )
                result.append(truncated)
                remaining = 0
                logger.warning(
                    "file_context_truncated",
                    filename=ctx.filename,
                    original_chars=text_len,
                    truncated_chars=remaining,
                )
            else:
                logger.warning(
                    "file_context_dropped",
                    filename=ctx.filename,
                    chars=text_len,
                )

        # Add image contexts back (they don't consume text budget)
        result.extend(image_contexts)
        return result


class FileContextLoader:
    """Loads attachment content from disk for prompt injection."""

    @staticmethod
    async def load(engine, attachment_ids: list[UUID]) -> list[AttachmentContext]:
        """Load attachment content for the given IDs.

        - Extracted documents: reads the sidecar .txt file
        - Direct-read files (CSV, TXT, JSON, etc.): reads from disk
        - Images: sets image_path for multimodal dispatch
        """
        if not attachment_ids:
            return []

        from nexus_core.models.attachments import objective_attachments

        async with engine.begin() as conn:
            result = await conn.execute(
                objective_attachments.select().where(
                    objective_attachments.c.attachment_id.in_(attachment_ids)
                )
            )
            rows = result.fetchall()

        contexts: list[AttachmentContext] = []
        for row in rows:
            ctx = AttachmentContext(
                attachment_id=row.attachment_id,
                filename=row.original_filename,
                content_type=row.content_type,
                size_bytes=row.size_bytes,
            )

            stored = Path(row.stored_path)

            # Image files — set path for multimodal dispatch
            if is_image(row.original_filename):
                if stored.exists():
                    ctx.image_path = stored
                contexts.append(ctx)
                continue

            # Extracted documents — read sidecar .txt
            if row.extraction_text_path:
                sidecar = Path(row.extraction_text_path)
                if sidecar.exists():
                    try:
                        ctx.text_content = await asyncio.to_thread(
                            sidecar.read_text, "utf-8"
                        )
                    except Exception as exc:
                        logger.warning(
                            "sidecar_read_failed",
                            filename=row.original_filename,
                            error=str(exc),
                        )
                contexts.append(ctx)
                continue

            # Direct-read files (csv, txt, json, etc.)
            if is_direct_read(row.original_filename) and stored.exists():
                try:
                    ctx.text_content = await asyncio.to_thread(
                        stored.read_text, "utf-8"
                    )
                except Exception as exc:
                    logger.warning(
                        "direct_read_failed",
                        filename=row.original_filename,
                        error=str(exc),
                    )

            contexts.append(ctx)

        logger.info(
            "file_context_loaded",
            attachment_count=len(contexts),
            text_count=sum(1 for c in contexts if c.text_content),
            image_count=sum(1 for c in contexts if c.image_path),
        )

        return contexts
