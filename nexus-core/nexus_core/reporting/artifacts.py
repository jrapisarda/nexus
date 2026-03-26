"""Filesystem helpers for report artifact discovery and preview."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from nexus_core.config import NexusSettings
from nexus_core.reporting.markdown_reports import _get_question_dir, _get_reports_root


@dataclass(slots=True)
class ReportArtifactSummary:
    """A report artifact visible to the dashboard and KG workbench."""

    title: str
    slug: str
    artifact_type: str
    objective_id: UUID
    finding_id: UUID | None
    version: str
    updated_at: datetime
    size_bytes: int


def list_question_artifacts(
    *,
    settings: NexusSettings | None,
    objective_id: UUID,
    objective_title: str,
) -> list[ReportArtifactSummary]:
    """List report artifacts for a root objective dossier."""
    reports_root = _get_reports_root(settings)
    question_dir = _get_question_dir(reports_root, objective_title, objective_id)
    if not question_dir.exists():
        return []

    artifacts: list[ReportArtifactSummary] = []
    for path in sorted(question_dir.rglob("*"), key=lambda item: item.name):
        if not path.is_file():
            continue
        artifact = _build_artifact_summary(reports_root=reports_root, objective_id=objective_id, path=path)
        if artifact is not None:
            artifacts.append(artifact)
    artifacts.sort(key=lambda item: item.updated_at, reverse=True)
    return artifacts


def list_finding_artifacts(
    *,
    settings: NexusSettings | None,
    objective_id: UUID,
    objective_title: str,
    finding_id: UUID,
) -> list[ReportArtifactSummary]:
    """List dossier files directly tied to a specific finding."""
    return [
        artifact
        for artifact in list_question_artifacts(
            settings=settings,
            objective_id=objective_id,
            objective_title=objective_title,
        )
        if artifact.finding_id == finding_id
    ]


def read_report_artifact(
    *,
    settings: NexusSettings | None,
    slug: str,
) -> dict[str, Any]:
    """Read an artifact under the reports root with path-traversal protection."""
    reports_root = _get_reports_root(settings).resolve()
    candidate = (reports_root / slug).resolve()
    if reports_root not in candidate.parents and candidate != reports_root:
        raise ValueError("Artifact path escapes reports root")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(slug)

    return {
        "slug": slug.replace("\\", "/"),
        "title": candidate.name,
        "artifact_type": _classify_artifact(candidate),
        "updated_at": datetime.fromtimestamp(candidate.stat().st_mtime),
        "size_bytes": candidate.stat().st_size,
        "content": candidate.read_text(encoding="utf-8"),
    }


def _build_artifact_summary(
    *,
    reports_root: Path,
    objective_id: UUID,
    path: Path,
) -> ReportArtifactSummary | None:
    artifact_type = _classify_artifact(path)
    if artifact_type == "other":
        return None

    finding_id = _extract_finding_id(path)
    version = "primary"
    if path.name.endswith(".v2.md"):
        version = "v2"

    title = _title_for_artifact(path, artifact_type)
    return ReportArtifactSummary(
        title=title,
        slug=path.relative_to(reports_root).as_posix(),
        artifact_type=artifact_type,
        objective_id=objective_id,
        finding_id=finding_id,
        version=version,
        updated_at=datetime.fromtimestamp(path.stat().st_mtime),
        size_bytes=path.stat().st_size,
    )


def _classify_artifact(path: Path) -> str:
    name = path.name
    if name == "recommendation-report.md":
        return "recommendation_report"
    if name == "recommendation-report.v2.md":
        return "recommendation_report"
    if name == "repair-note.md":
        return "repair_note"
    if name == "evidence-manifest.json":
        return "evidence_manifest"
    if "__approved-finding__" in name and name.endswith(".md"):
        return "finding_report"
    if name == "README.md":
        return "dossier_readme"
    return "other"


def _extract_finding_id(path: Path) -> UUID | None:
    if "__approved-finding__" not in path.name:
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"Finding ID: `([0-9a-fA-F-]{36})`", content)
    if match is None:
        return None
    try:
        return UUID(match.group(1))
    except ValueError:
        return None


def _title_for_artifact(path: Path, artifact_type: str) -> str:
    if artifact_type == "recommendation_report":
        return "Recommendation Report" if path.name == "recommendation-report.md" else "Recommendation Report v2"
    if artifact_type == "repair_note":
        return "Repair Note"
    if artifact_type == "evidence_manifest":
        return "Evidence Manifest"
    if artifact_type == "finding_report":
        return path.name
    if artifact_type == "dossier_readme":
        return "Question Dossier"
    return path.name
