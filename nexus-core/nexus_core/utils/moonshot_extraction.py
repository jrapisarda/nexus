"""Moonshot Files API extraction service for PDF/Excel/Word documents."""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from openai import AsyncOpenAI

from nexus_core.utils.file_context import is_extractable

logger = structlog.get_logger(__name__)

# Types that Moonshot's file-extract endpoint can parse
_EXTRACTABLE_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # .docx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    "application/vnd.ms-excel",  # .xls
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",  # .pptx
}


class MoonshotExtractionService:
    """Extracts text from documents using the Moonshot Files API.

    Reuses an existing ``AsyncOpenAI`` client instance (the same one
    used by :class:`KimiClient`) to share the connection pool.
    """

    def __init__(self, openai_client: AsyncOpenAI):
        self._client = openai_client

    async def extract(
        self,
        file_path: Path,
        content_type: str,
        timeout_secs: float = 120.0,
    ) -> tuple[str | None, str | None]:
        """Extract text from a document file via Moonshot.

        Returns:
            ``(extracted_text, moonshot_file_id)`` on success.
            ``(None, None)`` if the file type is not extractable or extraction fails.
        """
        # Only attempt extraction for supported types
        if content_type not in _EXTRACTABLE_MIMES and not is_extractable(file_path.name):
            return None, None

        try:
            # Step 1: Upload to Moonshot
            logger.info(
                "moonshot_extraction_started",
                filename=file_path.name,
                content_type=content_type,
            )

            file_object = await asyncio.wait_for(
                self._client.files.create(
                    file=file_path,
                    purpose="file-extract",
                ),
                timeout=timeout_secs,
            )

            moonshot_file_id = file_object.id

            # Step 2: Retrieve extracted text
            file_content = await asyncio.wait_for(
                self._client.files.content(moonshot_file_id),
                timeout=timeout_secs,
            )
            extracted_text = file_content.text

            if not extracted_text or not extracted_text.strip():
                logger.warning(
                    "moonshot_extraction_empty",
                    filename=file_path.name,
                    moonshot_file_id=moonshot_file_id,
                )
                return None, moonshot_file_id

            logger.info(
                "moonshot_extraction_complete",
                filename=file_path.name,
                moonshot_file_id=moonshot_file_id,
                chars_extracted=len(extracted_text),
            )

            return extracted_text, moonshot_file_id

        except asyncio.TimeoutError:
            logger.error(
                "moonshot_extraction_timeout",
                filename=file_path.name,
                timeout_secs=timeout_secs,
            )
            return None, None
        except Exception as exc:
            logger.error(
                "moonshot_extraction_failed",
                filename=file_path.name,
                error=str(exc),
            )
            return None, None

    async def write_sidecar(
        self,
        file_path: Path,
        extracted_text: str,
    ) -> Path:
        """Write extracted text to a sidecar ``.txt`` file next to the original.

        Returns the path to the sidecar file.
        """
        sidecar_path = file_path.with_suffix(file_path.suffix + ".txt")
        await asyncio.to_thread(sidecar_path.write_text, extracted_text, "utf-8")
        return sidecar_path

    async def delete_remote_file(self, moonshot_file_id: str) -> None:
        """Delete a file from Moonshot storage (cleanup)."""
        try:
            await self._client.files.delete(moonshot_file_id)
            logger.info(
                "moonshot_file_deleted",
                moonshot_file_id=moonshot_file_id,
            )
        except Exception as exc:
            logger.warning(
                "moonshot_file_delete_failed",
                moonshot_file_id=moonshot_file_id,
                error=str(exc),
            )
