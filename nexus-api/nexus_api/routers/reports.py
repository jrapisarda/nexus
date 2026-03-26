"""Filesystem-backed report artifact endpoints for the Observatory."""

from __future__ import annotations

from dataclasses import asdict
from uuid import UUID

from fastapi import APIRouter, HTTPException
import sqlalchemy as sa

from nexus_core.config import get_settings
from nexus_core.database import get_connection
from nexus_core.models.objectives import objectives
from nexus_core.reporting.artifacts import list_question_artifacts, read_report_artifact

from nexus_api.schemas import (
    ReportArtifactListResponse,
    ReportArtifactSummaryResponse,
    ReportFileResponse,
)

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/questions/{objective_id}", response_model=ReportArtifactListResponse)
async def list_reports_for_question(objective_id: UUID):
    """List dossier artifacts for a root question objective."""
    async with get_connection() as conn:
        objective_row = await conn.execute(
            sa.select(objectives.c.objective_id, objectives.c.title).where(
                objectives.c.objective_id == objective_id
            )
        )
        objective = objective_row.first()
        if objective is None:
            raise HTTPException(status_code=404, detail="Objective not found")

    items = list_question_artifacts(
        settings=get_settings(),
        objective_id=objective.objective_id,
        objective_title=objective.title,
    )
    return ReportArtifactListResponse(
        items=[ReportArtifactSummaryResponse(**asdict(item)) for item in items],
        count=len(items),
    )


@router.get("/files/{report_slug:path}", response_model=ReportFileResponse)
async def read_report_file(report_slug: str):
    """Read a report artifact for drawer preview."""
    try:
        artifact = read_report_artifact(
            settings=get_settings(),
            slug=report_slug,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Report artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ReportFileResponse(**artifact)
