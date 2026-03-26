"""Markdown report writer for validated findings and recommendation bundles."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
import json
import re
from typing import Any
from uuid import UUID

from nexus_core.config import NexusSettings


@dataclass(slots=True)
class ReviewNote:
    """Compact reviewer signal used in audit reports."""

    verdict: str
    confidence_rating: float
    methodology_critique: str = ""
    evidence_evaluation: str = ""
    novelty_assessment: str = ""
    revision_feedback: str = ""


@dataclass(slots=True)
class CitationRecord:
    """Structured citation captured from an agent finding or source ingest."""

    title: str
    source_type: str = ""
    source_name: str = ""
    url: str = ""
    doi: str = ""
    published_date: str = ""
    authors: list[str] = field(default_factory=list)
    supporting_snippet: str = ""
    source_finding_id: UUID | None = None
    derived: bool = False


@dataclass(slots=True)
class KGNodeDelta:
    """Node-level KG update recorded for an approved finding."""

    node_id: UUID
    label: str
    node_type: str
    action: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class KGEdgeDelta:
    """Edge-level KG update recorded for an approved finding."""

    edge_id: UUID
    source_label: str
    target_label: str
    relationship_type: str
    weight: float


@dataclass(slots=True)
class KGNodeReference:
    """A node referenced in a recommendation evidence set."""

    node_id: UUID
    label: str
    node_type: str
    status: str
    confidence_score: float


@dataclass(slots=True)
class KGEdgeReference:
    """An edge referenced in a recommendation evidence set."""

    edge_id: UUID
    source_label: str
    target_label: str
    relationship_type: str
    status: str
    confidence_score: float
    weight: float


@dataclass(slots=True)
class KGWriteSummary:
    """Summary of what was persisted to the knowledge graph."""

    nodes: list[KGNodeDelta] = field(default_factory=list)
    edges: list[KGEdgeDelta] = field(default_factory=list)

    @property
    def created_node_count(self) -> int:
        return sum(1 for node in self.nodes if node.action == "created")

    @property
    def merged_node_count(self) -> int:
        return sum(1 for node in self.nodes if node.action != "created")


@dataclass(slots=True)
class RecommendationSourceFinding:
    """Finding rolled into a final recommendation."""

    finding_id: UUID
    objective_id: UUID
    objective_title: str
    title: str
    content: str
    status: str = "validated"
    finding_type: str = "research"
    impact_level: str = "routine"
    review_round: int = 0
    kg_node_refs: list[str] = field(default_factory=list)
    kg_edge_refs: list[str] = field(default_factory=list)
    citations: list[CitationRecord] = field(default_factory=list)


@dataclass(slots=True)
class RecommendationSummary:
    """Final recommendation summary for a root question."""

    question_objective_id: UUID
    question_title: str
    synthesis_finding_id: UUID
    synthesis_instance_id: UUID
    synthesizer_name: str
    recommendation_markdown: str
    source_findings: list[RecommendationSourceFinding] = field(default_factory=list)
    source_selection_policy: str = "accepted_descendants"
    why_this_follows: str = ""
    citations: list[CitationRecord] = field(default_factory=list)
    kg_nodes: list[KGNodeReference] = field(default_factory=list)
    kg_edges: list[KGEdgeReference] = field(default_factory=list)
    contested_findings: list[RecommendationSourceFinding] = field(default_factory=list)
    repair_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RecommendationArtifactBundle:
    """Filesystem outputs for a recommendation report."""

    report_path: Path
    manifest_path: Path
    repair_note_path: Path | None = None


def write_finding_report(
    *,
    settings: NexusSettings | None,
    root_objective_id: UUID,
    root_objective_title: str,
    root_objective_status: str,
    objective_id: UUID,
    objective_title: str,
    objective_type: str,
    objective_description: str,
    finding_id: UUID,
    finding_title: str,
    finding_type: str,
    finding_content: str,
    impact_level: str,
    author_persona_name: str,
    review_round: int,
    mean_review_confidence: float,
    support_ratio: float,
    approval_count: int,
    revise_count: int,
    reject_count: int,
    reviewer_count: int,
    required_consensus: str,
    verdict_breakdown: dict[str, int],
    reviewers: list[ReviewNote],
    kg_summary: KGWriteSummary,
    citations: list[CitationRecord] | None = None,
) -> Path:
    """Write a detailed report for a validated finding."""
    reports_root = _get_reports_root(settings)
    question_dir = _get_question_dir(reports_root, root_objective_title, root_objective_id)
    findings_dir = question_dir / "findings"
    findings_dir.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now(UTC)
    filename = (
        f"{created_at:%Y%m%d-%H%M%S}__approved-finding__{str(finding_id)[:8]}.md"
    )
    report_path = findings_dir / filename
    report_path.write_text(
        _render_finding_report(
            created_at=created_at,
            root_objective_id=root_objective_id,
            root_objective_title=root_objective_title,
            root_objective_status=root_objective_status,
            objective_id=objective_id,
            objective_title=objective_title,
            objective_type=objective_type,
            objective_description=objective_description,
            finding_id=finding_id,
            finding_title=finding_title,
            finding_type=finding_type,
            finding_content=finding_content,
            impact_level=impact_level,
            author_persona_name=author_persona_name,
            review_round=review_round,
            mean_review_confidence=mean_review_confidence,
            support_ratio=support_ratio,
            approval_count=approval_count,
            revise_count=revise_count,
            reject_count=reject_count,
            reviewer_count=reviewer_count,
            required_consensus=required_consensus,
            verdict_breakdown=verdict_breakdown,
            reviewers=reviewers,
            kg_summary=kg_summary,
            citations=citations or [],
        ),
        encoding="utf-8",
    )

    _refresh_question_readme(
        question_dir=question_dir,
        question_title=root_objective_title,
        question_objective_id=root_objective_id,
        question_status=root_objective_status,
    )
    _refresh_index(reports_root)
    return report_path


def write_recommendation_report(
    *,
    settings: NexusSettings | None,
    summary: RecommendationSummary,
    question_status: str,
) -> RecommendationArtifactBundle:
    """Write the primary recommendation report and evidence manifest."""
    return _write_recommendation_bundle(
        settings=settings,
        summary=summary,
        question_status=question_status,
        report_filename="recommendation-report.md",
        repair_note=None,
    )


def write_repaired_recommendation_report(
    *,
    settings: NexusSettings | None,
    summary: RecommendationSummary,
    question_status: str,
    repair_reason: str,
    repaired_from: str = "recommendation-report.md",
) -> RecommendationArtifactBundle:
    """Write a versioned repaired recommendation report without overwriting history."""
    repair_note = _render_repair_note(
        created_at=datetime.now(UTC),
        summary=summary,
        repaired_from=repaired_from,
        repair_reason=repair_reason,
    )
    return _write_recommendation_bundle(
        settings=settings,
        summary=summary,
        question_status=question_status,
        report_filename="recommendation-report.v2.md",
        repair_note=repair_note,
    )


def _write_recommendation_bundle(
    *,
    settings: NexusSettings | None,
    summary: RecommendationSummary,
    question_status: str,
    report_filename: str,
    repair_note: str | None,
) -> RecommendationArtifactBundle:
    reports_root = _get_reports_root(settings)
    question_dir = _get_question_dir(
        reports_root,
        summary.question_title,
        summary.question_objective_id,
    )
    question_dir.mkdir(parents=True, exist_ok=True)

    report_path = question_dir / report_filename
    manifest_path = question_dir / "evidence-manifest.json"
    repair_note_path = question_dir / "repair-note.md" if repair_note else None

    report_path.write_text(
        _render_recommendation_report(
            summary=summary,
            question_status=question_status,
            manifest_path=manifest_path.name,
        ),
        encoding="utf-8",
    )
    manifest_path.write_text(
        json.dumps(
            _build_evidence_manifest(
                summary=summary,
                question_status=question_status,
                report_filename=report_filename,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    if repair_note_path is not None:
        repair_note_path.write_text(repair_note, encoding="utf-8")

    _refresh_question_readme(
        question_dir=question_dir,
        question_title=summary.question_title,
        question_objective_id=summary.question_objective_id,
        question_status=question_status,
    )
    _refresh_index(reports_root)
    return RecommendationArtifactBundle(
        report_path=report_path,
        manifest_path=manifest_path,
        repair_note_path=repair_note_path,
    )


def _render_finding_report(
    *,
    created_at: datetime,
    root_objective_id: UUID,
    root_objective_title: str,
    root_objective_status: str,
    objective_id: UUID,
    objective_title: str,
    objective_type: str,
    objective_description: str,
    finding_id: UUID,
    finding_title: str,
    finding_type: str,
    finding_content: str,
    impact_level: str,
    author_persona_name: str,
    review_round: int,
    mean_review_confidence: float,
    support_ratio: float,
    approval_count: int,
    revise_count: int,
    reject_count: int,
    reviewer_count: int,
    required_consensus: str,
    verdict_breakdown: dict[str, int],
    reviewers: list[ReviewNote],
    kg_summary: KGWriteSummary,
    citations: list[CitationRecord],
) -> str:
    verdict_bits = ", ".join(
        f"{key}: {value}" for key, value in sorted(verdict_breakdown.items())
    ) or "No verdict breakdown recorded"
    lines = [
        "# Approved Finding Report",
        "",
        f"Generated: {created_at.isoformat()}",
        "",
        "## Decision Snapshot",
        f"- Root question: {root_objective_title}",
        f"- Root objective ID: `{root_objective_id}`",
        f"- Root objective status at write time: `{root_objective_status}`",
        f"- Objective: {objective_title}",
        f"- Objective ID: `{objective_id}`",
        f"- Objective type: `{objective_type}`",
        f"- Finding: {finding_title}",
        f"- Finding ID: `{finding_id}`",
        f"- Finding type: `{finding_type}`",
        f"- Author persona: {author_persona_name}",
        f"- Impact level: `{impact_level}`",
        f"- Review round: `{review_round}`",
        f"- Mean review confidence: `{mean_review_confidence:.3f}`",
        f"- Support ratio: `{support_ratio:.3f}`",
        f"- Review votes: `{approval_count}` approve / `{revise_count}` revise / `{reject_count}` reject",
        f"- Reviewer count: `{reviewer_count}`",
        f"- Acceptance rule: {required_consensus}",
        f"- Verdict mix: {verdict_bits}",
        "",
        "## Why NEXUS Stored This",
        (
            "This finding entered the long-lived research record because peer review "
            "cleared the acceptance rule above, and the extracted entities and "
            "relationships were specific enough to justify knowledge-graph updates."
        ),
        "",
        "## Objective Context",
        objective_description.strip() or "No objective description recorded.",
        "",
        "## Finding Content",
        finding_content.strip() or "No finding content recorded.",
        "",
    ]
    if citations:
        lines.extend(["## Cited Articles And Sources", ""])
        for citation in citations:
            lines.extend(_render_citation_block(citation, heading_level=3))
    else:
        lines.extend(["## Cited Articles And Sources", "", "No structured citations were recorded for this finding.", ""])

    lines.extend(["## Reviewer Signals", ""])
    if reviewers:
        for index, review in enumerate(reviewers, start=1):
            lines.extend(
                [
                    f"### Reviewer {index}",
                    f"- Verdict: `{review.verdict}`",
                    f"- Confidence: `{review.confidence_rating:.3f}`",
                    f"- Methodology critique: {_safe_line(review.methodology_critique)}",
                    f"- Evidence evaluation: {_safe_line(review.evidence_evaluation)}",
                    f"- Novelty assessment: {_safe_line(review.novelty_assessment)}",
                    f"- Revision feedback: {_safe_line(review.revision_feedback)}",
                    "",
                ]
            )
    else:
        lines.append("No reviewer notes were captured.")
        lines.append("")

    lines.extend(
        [
            "## Knowledge Graph Write Set",
            f"- Nodes touched: `{len(kg_summary.nodes)}`",
            f"- Nodes created: `{kg_summary.created_node_count}`",
            f"- Nodes merged into existing graph state: `{kg_summary.merged_node_count}`",
            f"- Edges created: `{len(kg_summary.edges)}`",
            "",
        ]
    )

    if kg_summary.nodes:
        lines.extend(["### Nodes", ""])
        for node in kg_summary.nodes:
            lines.extend(
                [
                    f"#### {node.label}",
                    f"- Node ID: `{node.node_id}`",
                    f"- Type: `{node.node_type}`",
                    f"- Action: `{node.action}`",
                    f"- Properties: `{json.dumps(node.properties or {}, sort_keys=True)}`",
                    "",
                ]
            )
    else:
        lines.extend(["No KG nodes were created or merged for this finding.", ""])

    if kg_summary.edges:
        lines.extend(["### Edges", ""])
        for edge in kg_summary.edges:
            lines.extend(
                [
                    f"- `{edge.source_label}` --[{edge.relationship_type} / weight={edge.weight:.2f}]--> `{edge.target_label}` (`{edge.edge_id}`)",
                ]
            )
        lines.append("")
    else:
        lines.extend(["No KG edges were created for this finding.", ""])

    lines.extend(
        [
            "## Storage Rationale",
            (
                "The KG write set above is the exact graph delta recorded from this "
                "approved finding. Created nodes represent new research state. Merged "
                "nodes indicate the finding strengthened or enriched an existing concept."
            ),
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _render_recommendation_report(
    *,
    summary: RecommendationSummary,
    question_status: str,
    manifest_path: str,
) -> str:
    total_node_refs = len(summary.kg_nodes)
    total_edge_refs = len(summary.kg_edges)
    contested_count = len(summary.contested_findings)
    lines = [
        "# Recommendation Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Final Decision",
        f"- Question: {summary.question_title}",
        f"- Root objective ID: `{summary.question_objective_id}`",
        f"- Current status: `{question_status}`",
        f"- Synthesizer: {summary.synthesizer_name}",
        f"- Synthesis finding ID: `{summary.synthesis_finding_id}`",
        f"- Synthesis instance ID: `{summary.synthesis_instance_id}`",
        f"- Evidence selection policy: `{summary.source_selection_policy}`",
        "",
        "## Recommendation",
        summary.recommendation_markdown.strip() or "No recommendation text recorded.",
        "",
        "## Evidence Base Summary",
        f"- Source findings used: `{len(summary.source_findings)}`",
        f"- Referenced KG nodes: `{total_node_refs}`",
        f"- Referenced KG edges: `{total_edge_refs}`",
        f"- Cited articles and sources: `{len(summary.citations)}`",
        f"- Contested evidence items: `{contested_count}`",
        f"- Evidence manifest: `{manifest_path}`",
        "",
        "## Why This Recommendation Follows",
        summary.why_this_follows.strip()
        or (
            "This recommendation was synthesized from the accepted branch outputs below. "
            "Each branch either remains validated or was later challenged and is clearly "
            "badged as contested so an operator can judge the remaining support."
        ),
        "",
        "## Cited Articles And Sources",
        "",
    ]

    if summary.citations:
        for citation in summary.citations:
            lines.extend(_render_citation_block(citation, heading_level=3))
    else:
        lines.extend(
            [
                "No structured citations were available for this recommendation.",
                "",
            ]
        )

    lines.extend(["## Knowledge Graph References", ""])
    if summary.kg_nodes:
        lines.append("### Nodes")
        lines.append("")
        for node in summary.kg_nodes:
            lines.append(
                f"- `{node.label}` (`{node.node_type}` | `{node.status}` | confidence `{node.confidence_score:.3f}` | `{node.node_id}`)"
            )
        lines.append("")
    else:
        lines.extend(["No KG node references were attached to this recommendation.", ""])

    if summary.kg_edges:
        lines.append("### Edges")
        lines.append("")
        for edge in summary.kg_edges:
            lines.append(
                f"- `{edge.source_label}` --[{edge.relationship_type} / weight={edge.weight:.2f}]--> `{edge.target_label}` "
                f"(`{edge.status}` | confidence `{edge.confidence_score:.3f}` | `{edge.edge_id}`)"
            )
        lines.append("")
    else:
        lines.extend(["No KG edge references were attached to this recommendation.", ""])

    if summary.contested_findings:
        lines.extend(["## Contested Evidence", ""])
        for finding in summary.contested_findings:
            lines.extend(
                [
                    f"### {finding.title}",
                    f"- Finding ID: `{finding.finding_id}`",
                    f"- Source objective: {finding.objective_title}",
                    f"- Current status: `{finding.status}`",
                    f"- Impact level: `{finding.impact_level}`",
                    f"- Review round: `{finding.review_round}`",
                    "",
                    finding.content.strip() or "No content recorded.",
                    "",
                ]
            )
    else:
        lines.extend(["## Contested Evidence", "", "No source findings in this recommendation are currently challenged.", ""])

    lines.extend(
        [
            "## Source Findings",
            "",
        ]
    )

    if summary.source_findings:
        for finding in summary.source_findings:
            lines.extend(
                [
                    f"### {finding.title}",
                    f"- Finding ID: `{finding.finding_id}`",
                    f"- Source objective: {finding.objective_title}",
                    f"- Source objective ID: `{finding.objective_id}`",
                    f"- Finding type: `{finding.finding_type}`",
                    f"- Current status: `{finding.status}`",
                    f"- Impact level: `{finding.impact_level}`",
                    f"- Review round: `{finding.review_round}`",
                    f"- KG node refs: `{', '.join(finding.kg_node_refs) or 'none'}`",
                    f"- KG edge refs: `{', '.join(finding.kg_edge_refs) or 'none'}`",
                    f"- Structured citations: `{len(finding.citations)}`",
                    "",
                    finding.content.strip() or "No source finding content recorded.",
                    "",
                ]
            )
    else:
        lines.extend(
            [
                "No accepted descendant findings were attached to this recommendation.",
                "",
            ]
        )

    lines.extend(
        [
            "## Dossier Navigation",
            "- Approved finding dossiers live in the sibling `findings/` directory.",
            "- Question summary lives in `README.md` for this dossier folder.",
            "- The machine-readable evidence ledger is stored in `evidence-manifest.json`.",
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _build_evidence_manifest(
    *,
    summary: RecommendationSummary,
    question_status: str,
    report_filename: str,
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat()
    return {
        "version": 1,
        "generated_at": generated_at,
        "question": {
            "objective_id": str(summary.question_objective_id),
            "title": summary.question_title,
            "status": question_status,
        },
        "report": {
            "filename": report_filename,
            "synthesis_finding_id": str(summary.synthesis_finding_id),
            "synthesis_instance_id": str(summary.synthesis_instance_id),
            "synthesizer_name": summary.synthesizer_name,
            "source_selection_policy": summary.source_selection_policy,
            "repair_metadata": _jsonify(summary.repair_metadata),
        },
        "citations": [_citation_to_dict(item) for item in summary.citations],
        "kg_nodes": [_jsonify(asdict(node)) for node in summary.kg_nodes],
        "kg_edges": [_jsonify(asdict(edge)) for edge in summary.kg_edges],
        "source_findings": [
            {
                "finding_id": str(finding.finding_id),
                "objective_id": str(finding.objective_id),
                "objective_title": finding.objective_title,
                "title": finding.title,
                "status": finding.status,
                "finding_type": finding.finding_type,
                "impact_level": finding.impact_level,
                "review_round": finding.review_round,
                "kg_node_refs": list(finding.kg_node_refs),
                "kg_edge_refs": list(finding.kg_edge_refs),
                "citations": [_citation_to_dict(item) for item in finding.citations],
            }
            for finding in summary.source_findings
        ],
        "contested_findings": [
            {
                "finding_id": str(finding.finding_id),
                "title": finding.title,
                "status": finding.status,
                "objective_id": str(finding.objective_id),
            }
            for finding in summary.contested_findings
        ],
    }


def _render_repair_note(
    *,
    created_at: datetime,
    summary: RecommendationSummary,
    repaired_from: str,
    repair_reason: str,
) -> str:
    lines = [
        "# Recommendation Report Repair Note",
        "",
        f"Generated: {created_at.isoformat()}",
        "",
        "## Repair Scope",
        f"- Question: {summary.question_title}",
        f"- Root objective ID: `{summary.question_objective_id}`",
        f"- Repaired from: `{repaired_from}`",
        f"- New report: `recommendation-report.v2.md`",
        f"- Reason: {repair_reason}",
        "",
        "## What Was Reconstructed",
        f"- Accepted descendant source findings: `{len(summary.source_findings)}`",
        f"- KG nodes recovered: `{len(summary.kg_nodes)}`",
        f"- KG edges recovered: `{len(summary.kg_edges)}`",
        f"- Structured citations recovered: `{len(summary.citations)}`",
        "",
        "## Audit Note",
        (
            "This repair preserves the original recommendation report for auditability. "
            "Recovered evidence is limited to the structured citations and knowledge-graph "
            "references persisted in the historical record."
        ),
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def _render_citation_block(citation: CitationRecord, *, heading_level: int) -> list[str]:
    heading = "#" * heading_level
    authors = ", ".join(citation.authors) if citation.authors else "Unknown authors"
    details = [
        f"{heading} {citation.title}",
        f"- Source type: `{citation.source_type or 'unknown'}`",
        f"- Source name: {citation.source_name or 'Unknown source'}",
        f"- URL: {citation.url or 'Not recorded'}",
        f"- DOI: {citation.doi or 'Not recorded'}",
        f"- Published date: {citation.published_date or 'Not recorded'}",
        f"- Authors: {authors}",
    ]
    if citation.supporting_snippet:
        details.append(f"- Supporting snippet: {_safe_line(citation.supporting_snippet)}")
    if citation.source_finding_id is not None:
        details.append(f"- Source finding ID: `{citation.source_finding_id}`")
    details.append("")
    return details


def _refresh_question_readme(
    *,
    question_dir: Path,
    question_title: str,
    question_objective_id: UUID,
    question_status: str,
) -> None:
    findings_dir = question_dir / "findings"
    finding_reports = sorted(findings_dir.glob("*.md"), reverse=True)
    recommendation_reports = sorted(
        question_dir.glob("recommendation-report*.md"),
        key=lambda path: path.name,
    )
    manifest_path = question_dir / "evidence-manifest.json"
    repair_note_path = question_dir / "repair-note.md"

    lines = [
        "# Question Dossier",
        "",
        f"- Question: {question_title}",
        f"- Root objective ID: `{question_objective_id}`",
        f"- Current status: `{question_status}`",
        f"- Approved finding reports: `{len(finding_reports)}`",
        f"- Recommendation reports: `{len(recommendation_reports)}`",
        f"- Evidence manifest available: `{'yes' if manifest_path.exists() else 'no'}`",
        f"- Repair note available: `{'yes' if repair_note_path.exists() else 'no'}`",
        "",
        "## Navigation",
    ]
    if recommendation_reports:
        for report_path in recommendation_reports:
            lines.append(f"- [{report_path.name}]({report_path.name})")
    else:
        lines.append("- Recommendation report not generated yet.")

    if manifest_path.exists():
        lines.append("- [Evidence Manifest](evidence-manifest.json)")
    if repair_note_path.exists():
        lines.append("- [Repair Note](repair-note.md)")

    if finding_reports:
        lines.append("- Approved Finding Reports:")
        lines.extend(
            [
                f"  - [{path.name}](findings/{path.name})"
                for path in finding_reports
            ]
        )
    else:
        lines.append("- No approved finding reports generated yet.")

    (question_dir / "README.md").write_text(
        "\n".join(lines).strip() + "\n",
        encoding="utf-8",
    )


def _refresh_index(reports_root: Path) -> None:
    questions_dir = reports_root / "questions"
    dossier_dirs = sorted(
        [path for path in questions_dir.glob("*") if path.is_dir()],
        key=lambda path: path.name,
    )
    lines = [
        "# NEXUS Reports Index",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Question Dossiers",
    ]
    if dossier_dirs:
        for dossier_dir in dossier_dirs:
            recommendation_paths = list(dossier_dir.glob("recommendation-report*.md"))
            finding_count = len(list((dossier_dir / "findings").glob("*.md")))
            manifest_exists = (dossier_dir / "evidence-manifest.json").exists()
            lines.append(
                f"- [{dossier_dir.name}](questions/{dossier_dir.name}/README.md) "
                f"(approved findings: {finding_count}, recommendation reports: {len(recommendation_paths)}, "
                f"manifest: {'yes' if manifest_exists else 'no'})"
            )
    else:
        lines.append("- No question dossiers generated yet.")

    (reports_root / "INDEX.md").write_text(
        "\n".join(lines).strip() + "\n",
        encoding="utf-8",
    )


def _get_question_dir(reports_root: Path, question_title: str, objective_id: UUID) -> Path:
    question_dir = reports_root / "questions" / (
        f"{_slugify(question_title)[:72]}__{str(objective_id)[:8]}"
    )
    question_dir.mkdir(parents=True, exist_ok=True)
    return question_dir


def _get_reports_root(settings: NexusSettings | None) -> Path:
    configured = getattr(settings, "REPORTS_DIR", "reports")
    path = Path(configured)
    if not path.is_absolute():
        path = _find_repo_root() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "README.md").exists() and (parent / "nexus-engine").exists():
            return parent
    return Path.cwd()


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "question"


def _safe_line(value: str) -> str:
    compact = " ".join((value or "").split())
    return compact or "None recorded."


def _citation_to_dict(citation: CitationRecord) -> dict[str, Any]:
    payload = _jsonify(asdict(citation))
    if payload.get("source_finding_id") is not None:
        payload["source_finding_id"] = str(payload["source_finding_id"])
    return payload


def _jsonify(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, list):
        return [_jsonify(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonify(item) for key, item in value.items()}
    return value
