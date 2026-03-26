"""File upload endpoints for the NEXUS Observatory API."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import filetype
import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile

from nexus_core.config import get_settings
from nexus_core.database import get_connection
from nexus_core.models.attachments import objective_attachments
from nexus_core.utils.file_context import (
    ALLOWED_EXTENSIONS,
    is_extractable,
    sanitize_filename,
    validate_extension,
)

from nexus_api.schemas import FileUploadResponse

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("", response_model=FileUploadResponse)
async def upload_file(file: UploadFile, background_tasks: BackgroundTasks):
    """Upload a research context file.

    Returns attachment metadata with an ``attachment_id`` that can be
    referenced when submitting an objective.
    """
    settings = get_settings()

    # -- Validate filename extension --------------------------------------
    original_filename = file.filename or "unnamed"
    if not validate_extension(original_filename):
        raise HTTPException(
            status_code=422,
            detail=(
                f"File type not allowed. Accepted extensions: "
                f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )

    # -- Stream-read with size enforcement --------------------------------
    max_size = settings.MAX_FILE_SIZE_BYTES
    chunks: list[bytes] = []
    total_size = 0

    while True:
        chunk = await file.read(1024 * 256)  # 256KB chunks
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds maximum size of {max_size // (1024 * 1024)}MB",
            )
        chunks.append(chunk)

    if total_size == 0:
        raise HTTPException(status_code=422, detail="Empty file")

    file_bytes = b"".join(chunks)

    # -- Validate magic bytes ---------------------------------------------
    kind = filetype.guess(file_bytes[:2048])
    # For plain-text types (csv, tsv, txt, json, md) filetype returns None
    # since they have no magic bytes — that's expected and allowed.
    content_type = file.content_type or "application/octet-stream"
    if kind is not None:
        content_type = kind.mime

    # -- Write to disk ----------------------------------------------------
    safe_name = sanitize_filename(original_filename)
    file_uuid = str(uuid4())
    upload_dir = Path(settings.UPLOADS_DIR) / "pending"
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{file_uuid}_{safe_name}"
    stored_path = upload_dir / stored_filename
    stored_path.write_bytes(file_bytes)

    # -- Insert DB row ----------------------------------------------------
    async with get_connection() as conn:
        async with conn.begin():
            result = await conn.execute(
                objective_attachments.insert()
                .values(
                    original_filename=original_filename,
                    stored_path=str(stored_path.resolve()),
                    content_type=content_type,
                    size_bytes=total_size,
                    upload_status="uploaded",
                )
                .returning(
                    objective_attachments.c.attachment_id,
                    objective_attachments.c.created_at,
                )
            )
            row = result.first()

    logger.info(
        "file_upload_received",
        attachment_id=str(row.attachment_id),
        filename=original_filename,
        size_bytes=total_size,
        content_type=content_type,
    )

    # -- Trigger extraction in background for extractable types -----------
    if is_extractable(original_filename):
        background_tasks.add_task(
            _extract_document,
            attachment_id=row.attachment_id,
            stored_path=stored_path,
            content_type=content_type,
        )

    return FileUploadResponse(
        attachment_id=row.attachment_id,
        original_filename=original_filename,
        content_type=content_type,
        size_bytes=total_size,
        upload_status="uploaded",
        created_at=row.created_at,
    )


@router.get("/{attachment_id}", response_model=FileUploadResponse)
async def get_attachment(attachment_id: str):
    """Get metadata for an uploaded file."""
    from uuid import UUID

    try:
        att_uuid = UUID(attachment_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid attachment ID")

    async with get_connection() as conn:
        result = await conn.execute(
            objective_attachments.select().where(
                objective_attachments.c.attachment_id == att_uuid
            )
        )
        row = result.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Attachment not found")

    return FileUploadResponse(
        attachment_id=row.attachment_id,
        original_filename=row.original_filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        upload_status=row.upload_status,
        created_at=row.created_at,
    )


async def _extract_document(
    attachment_id,
    stored_path: Path,
    content_type: str,
) -> None:
    """Background task: extract text from a document via Moonshot Files API."""
    try:
        from nexus_core.config import get_settings
        from nexus_core.utils.moonshot_extraction import MoonshotExtractionService
        from openai import AsyncOpenAI

        settings = get_settings()
        client = AsyncOpenAI(
            api_key=settings.MOONSHOT_API_KEY,
            base_url=settings.MOONSHOT_BASE_URL,
        )
        service = MoonshotExtractionService(client)

        extracted_text, moonshot_file_id = await service.extract(
            stored_path, content_type
        )

        if extracted_text:
            sidecar_path = await service.write_sidecar(stored_path, extracted_text)
            async with get_connection() as conn:
                async with conn.begin():
                    await conn.execute(
                        objective_attachments.update()
                        .where(
                            objective_attachments.c.attachment_id == attachment_id
                        )
                        .values(
                            upload_status="extracted",
                            extraction_text_path=str(sidecar_path.resolve()),
                            moonshot_file_id=moonshot_file_id,
                        )
                    )
            logger.info(
                "background_extraction_complete",
                attachment_id=str(attachment_id),
            )
        else:
            async with get_connection() as conn:
                async with conn.begin():
                    await conn.execute(
                        objective_attachments.update()
                        .where(
                            objective_attachments.c.attachment_id == attachment_id
                        )
                        .values(
                            upload_status="extraction_failed",
                            moonshot_file_id=moonshot_file_id,
                        )
                    )
            logger.warning(
                "background_extraction_failed",
                attachment_id=str(attachment_id),
            )

        await client.close()

    except Exception as exc:
        logger.error(
            "background_extraction_error",
            attachment_id=str(attachment_id),
            error=str(exc),
        )
