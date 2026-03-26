from uuid import uuid4

from nexus_core.config import NexusSettings
from nexus_core.reporting import (
    CitationRecord,
    KGEdgeDelta,
    KGNodeDelta,
    KGWriteSummary,
    RecommendationSourceFinding,
    RecommendationSummary,
    ReviewNote,
    write_finding_report,
    write_recommendation_report,
)


def test_write_finding_report_creates_question_dossier(tmp_path):
    reports_dir = tmp_path / "reports"
    settings = NexusSettings(REPORTS_DIR=str(reports_dir))
    root_objective_id = uuid4()
    finding_id = uuid4()

    report_path = write_finding_report(
        settings=settings,
        root_objective_id=root_objective_id,
        root_objective_title="How do we mitigate job loss due to AI?",
        root_objective_status="active",
        objective_id=uuid4(),
        objective_title="Evaluate labor transition options",
        objective_type="strategic",
        objective_description="Compare safety nets, retraining, and policy sequencing.",
        finding_id=finding_id,
        finding_title="Transition policies reduce displacement shock",
        finding_type="research",
        finding_content="A blended policy stack outperforms isolated interventions.",
        impact_level="high-impact",
        author_persona_name="Systems Synthesizer",
        review_round=1,
        mean_review_confidence=0.81,
        support_ratio=0.85,
        approval_count=2,
        revise_count=1,
        reject_count=0,
        reviewer_count=3,
        required_consensus="two-thirds support with no rejects",
        verdict_breakdown={"approve": 2, "revise": 1},
        reviewers=[
            ReviewNote(
                verdict="approve",
                confidence_rating=0.84,
                methodology_critique="Solid comparative framing.",
                evidence_evaluation="Evidence is broad enough.",
                novelty_assessment="Good synthesis.",
                revision_feedback="Tighten the implementation appendix.",
            )
        ],
        kg_summary=KGWriteSummary(
            nodes=[
                KGNodeDelta(
                    node_id=uuid4(),
                    label="Retraining Credits",
                    node_type="concept",
                    action="created",
                    properties={"scope": "national"},
                )
            ],
            edges=[
                KGEdgeDelta(
                    edge_id=uuid4(),
                    source_label="Retraining Credits",
                    target_label="Job Retention",
                    relationship_type="improves",
                    weight=0.8,
                )
            ],
        ),
    )

    dossier_dir = report_path.parent.parent
    assert report_path.exists()
    assert (dossier_dir / "README.md").exists()
    assert (reports_dir / "INDEX.md").exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Approved Finding Report" in content
    assert "Why NEXUS Stored This" in content
    assert "Retraining Credits" in content


def test_write_recommendation_report_updates_question_dossier(tmp_path):
    reports_dir = tmp_path / "reports"
    settings = NexusSettings(REPORTS_DIR=str(reports_dir))
    question_objective_id = uuid4()

    artifact_bundle = write_recommendation_report(
        settings=settings,
        question_status="completed",
        summary=RecommendationSummary(
            question_objective_id=question_objective_id,
            question_title="How do we mitigate job loss due to AI?",
            synthesis_finding_id=uuid4(),
            synthesis_instance_id=uuid4(),
            synthesizer_name="Systems Synthesizer",
            recommendation_markdown="Prioritize wage insurance, targeted retraining, and regional transition funds.",
            source_findings=[
                RecommendationSourceFinding(
                    finding_id=uuid4(),
                    objective_id=uuid4(),
                    objective_title="Model displacement patterns",
                    title="Displacement clusters are regionally concentrated",
                    content="Risk is concentrated in routine cognitive and clerical sectors.",
                    status="challenged",
                    kg_node_refs=["node-1", "node-2"],
                    kg_edge_refs=["edge-1"],
                    citations=[
                        CitationRecord(
                            title="Labor displacement paper",
                            source_type="paper",
                            source_name="NBER",
                            url="https://example.com/paper",
                            supporting_snippet="Routine cognitive work is highly exposed.",
                        )
                    ],
                )
            ],
            citations=[
                CitationRecord(
                    title="Labor displacement paper",
                    source_type="paper",
                    source_name="NBER",
                    url="https://example.com/paper",
                    supporting_snippet="Routine cognitive work is highly exposed.",
                )
            ],
        ),
    )

    report_path = artifact_bundle.report_path
    dossier_dir = report_path.parent
    assert report_path.exists()
    assert artifact_bundle.manifest_path.exists()
    assert (dossier_dir / "README.md").exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Recommendation Report" in content
    assert "How do we mitigate job loss due to AI?" in content
    assert "Displacement clusters are regionally concentrated" in content
    assert "Cited Articles And Sources" in content
    assert "Contested Evidence" in content
    assert "derived/backfilled" not in content
