"""Unit tests for nexus_core.llm.prompt_builder — PromptBuilder."""

from pathlib import Path
from uuid import uuid4

import pytest

from nexus_core.llm.prompt_builder import PromptBuilder
from nexus_core.utils.file_context import AttachmentContext


# ---------------------------------------------------------------------------
# build_agent_prompt
# ---------------------------------------------------------------------------

class TestBuildAgentPrompt:

    def test_interpolates_objective(self):
        system, user = PromptBuilder.build_agent_prompt(
            persona_template="You are an agent. Objective: {objective}",
            objective_description="Test objective",
        )
        assert "Test objective" in system
        assert "Test objective" in user

    def test_interpolates_kg_context(self):
        system, user = PromptBuilder.build_agent_prompt(
            persona_template="Context: {kg_context}",
            objective_description="test",
            kg_context="Some KG data",
        )
        assert "Some KG data" in system
        assert "Some KG data" in user

    def test_interpolates_institutional_memory(self):
        system, user = PromptBuilder.build_agent_prompt(
            persona_template="Memory: {institutional_memory}",
            objective_description="test",
            institutional_memory="Lesson learned",
        )
        assert "Lesson learned" in system

    def test_empty_context_uses_default(self):
        system, user = PromptBuilder.build_agent_prompt(
            persona_template="Context: {kg_context}",
            objective_description="test",
            kg_context="",
        )
        assert "No prior knowledge" in system or "No prior knowledge" in user

    def test_returns_tuple_of_strings(self):
        result = PromptBuilder.build_agent_prompt("template {objective}", "desc")
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], str)

    def test_build_agent_prompt_interpolates_variables(self):
        """All three placeholders should be replaced in the system prompt."""
        template = (
            "You are an agent. Objective: {objective}. "
            "KG: {kg_context}. Memory: {institutional_memory}."
        )
        system, user = PromptBuilder.build_agent_prompt(
            persona_template=template,
            objective_description="Find the cure",
            kg_context="Node A -> Node B",
            institutional_memory="Lesson: always validate",
        )
        assert "Find the cure" in system
        assert "Node A -> Node B" in system
        assert "Lesson: always validate" in system
        assert "Find the cure" in user

    def test_build_agent_prompt_with_empty_context(self):
        """Empty kg_context and institutional_memory should produce default fallback text."""
        template = "Obj: {objective}. KG: {kg_context}. Mem: {institutional_memory}."
        system, user = PromptBuilder.build_agent_prompt(
            persona_template=template,
            objective_description="Test objective",
            kg_context="",
            institutional_memory="",
        )
        assert "No prior knowledge available." in system
        assert "No institutional memory available." in system
        assert "No prior knowledge graph context available" in user
        assert "No relevant institutional memory" in user

    def test_build_agent_prompt_with_none_defaults(self):
        """When optional params are omitted entirely, defaults should trigger."""
        template = "Obj: {objective}. KG: {kg_context}. Mem: {institutional_memory}."
        system, user = PromptBuilder.build_agent_prompt(
            persona_template=template,
            objective_description="Objective X",
        )
        assert "No prior knowledge available." in system
        assert "No institutional memory available." in system

    def test_build_agent_prompt_user_prompt_contains_json_schema(self):
        """User prompt should contain the expected JSON schema keys for findings output."""
        _, user = PromptBuilder.build_agent_prompt(
            persona_template="{objective}{kg_context}{institutional_memory}",
            objective_description="Test",
        )
        assert '"title"' in user
        assert '"content"' in user
        assert '"confidence"' in user
        assert '"citations"' in user
        assert '"kg_contribution"' in user
        assert '"entities"' in user
        assert '"relationships"' in user


# ---------------------------------------------------------------------------
# build_decomposition_prompt
# ---------------------------------------------------------------------------

class TestBuildDecompositionPrompt:

    def test_includes_title_and_description(self):
        system, user = PromptBuilder.build_decomposition_prompt(
            objective_title="Test Title",
            objective_description="Test Description",
        )
        assert "Test Title" in user
        assert "Test Description" in user

    def test_includes_max_depth(self):
        system, user = PromptBuilder.build_decomposition_prompt(
            objective_title="t", objective_description="d", max_depth=4
        )
        assert "4" in system

    def test_includes_max_fanout(self):
        system, user = PromptBuilder.build_decomposition_prompt(
            objective_title="t", objective_description="d", max_fanout=6
        )
        assert "6" in system

    def test_json_schema_in_user_prompt(self):
        _, user = PromptBuilder.build_decomposition_prompt("t", "d")
        assert "sub_objectives" in user
        assert "depends_on" in user

    def test_build_decomposition_prompt_includes_limits(self):
        """System prompt should reflect the custom max_depth and max_fanout values."""
        system, user = PromptBuilder.build_decomposition_prompt(
            objective_title="Cure cancer",
            objective_description="Find novel treatments",
            max_depth=4,
            max_fanout=6,
        )
        assert "4" in system
        assert "6" in system
        assert "Cure cancer" in user
        assert "Find novel treatments" in user

    def test_build_decomposition_prompt_default_limits_in_system(self):
        """Defaults max_depth=6, max_fanout=8 should appear in system prompt."""
        system, _ = PromptBuilder.build_decomposition_prompt(
            objective_title="Title",
            objective_description="Desc",
        )
        # "Maximum depth: 6 levels" and "Maximum fan-out: 8"
        assert "6" in system
        assert "8" in system

    def test_build_decomposition_prompt_empty_kg_context_fallback(self):
        """Empty KG context should produce fallback text in user prompt."""
        _, user = PromptBuilder.build_decomposition_prompt(
            objective_title="Title",
            objective_description="Desc",
            kg_context="",
        )
        assert "No prior knowledge available" in user

    def test_build_decomposition_prompt_with_kg_context(self):
        """Provided KG context should appear in the user prompt."""
        _, user = PromptBuilder.build_decomposition_prompt(
            objective_title="Title",
            objective_description="Desc",
            kg_context="Known: X implies Y",
        )
        assert "Known: X implies Y" in user

    def test_build_decomposition_prompt_has_role_class_schema(self):
        _, user = PromptBuilder.build_decomposition_prompt("Title", "Desc")
        assert '"role_class"' in user
        assert '"impact_level"' in user

    def test_build_decomposition_prompt_demands_raw_json_only(self):
        _, user = PromptBuilder.build_decomposition_prompt("Title", "Desc")
        assert "Return raw JSON only." in user
        assert "Do not wrap the JSON in markdown fences." in user


# ---------------------------------------------------------------------------
# build_review_prompt
# ---------------------------------------------------------------------------

class TestBuildReviewPrompt:

    def test_includes_finding(self):
        system, user = PromptBuilder.build_review_prompt(
            finding_title="Test Finding",
            finding_content="Finding content here",
        )
        assert "Test Finding" in user
        assert "Finding content here" in user

    def test_includes_impact_level(self):
        _, user = PromptBuilder.build_review_prompt("t", "c", impact_level="high-impact")
        assert "high-impact" in user

    def test_json_schema_in_prompt(self):
        _, user = PromptBuilder.build_review_prompt("t", "c")
        assert "verdict" in user
        assert "confidence_rating" in user

    def test_build_review_prompt_includes_finding(self):
        """Review prompt should include the finding title and content."""
        system, user = PromptBuilder.build_review_prompt(
            finding_title="Novel mechanism discovered",
            finding_content="We found that X causes Y via Z.",
        )
        assert "Novel mechanism discovered" in user
        assert "We found that X causes Y via Z." in user
        assert "peer reviewer" in system.lower()

    def test_build_review_prompt_default_impact_level_is_routine(self):
        _, user = PromptBuilder.build_review_prompt(
            finding_title="Title",
            finding_content="Content",
        )
        assert "routine" in user

    def test_build_review_prompt_has_methodology_critique_schema(self):
        _, user = PromptBuilder.build_review_prompt("Title", "Content")
        assert '"methodology_critique"' in user
        assert '"evidence_evaluation"' in user
        assert '"novelty_assessment"' in user


# ---------------------------------------------------------------------------
# build_challenge_prompt
# ---------------------------------------------------------------------------

class TestBuildChallengePrompt:

    def test_includes_finding_content(self):
        system, user = PromptBuilder.build_challenge_prompt(
            finding_title="Challenge This",
            finding_content="Some validated finding",
        )
        assert "Challenge This" in user
        assert "Some validated finding" in user

    def test_adversarial_framing(self):
        system, _ = PromptBuilder.build_challenge_prompt("t", "c")
        assert "Red Team" in system or "adversarial" in system or "flaw" in system

    def test_build_challenge_prompt_includes_content(self):
        """Challenge prompt should include the finding content."""
        system, user = PromptBuilder.build_challenge_prompt(
            finding_title="Hypothesis Alpha",
            finding_content="Alpha causes Beta under condition C",
        )
        assert "Hypothesis Alpha" in user
        assert "Alpha causes Beta under condition C" in user
        assert "Red Team" in system

    def test_build_challenge_prompt_with_kg_context(self):
        _, user = PromptBuilder.build_challenge_prompt(
            finding_title="Title",
            finding_content="Content",
            kg_context="Node X contradicts Node Y",
        )
        assert "Node X contradicts Node Y" in user

    def test_build_challenge_prompt_empty_kg_context_fallback(self):
        _, user = PromptBuilder.build_challenge_prompt(
            finding_title="Title",
            finding_content="Content",
            kg_context="",
        )
        assert "No additional context available." in user

    def test_build_challenge_prompt_has_flaw_schema(self):
        _, user = PromptBuilder.build_challenge_prompt("Title", "Content")
        assert '"has_flaw"' in user
        assert '"flaw_type"' in user
        assert '"severity"' in user
        assert '"counter_evidence"' in user


# ---------------------------------------------------------------------------
# build_synthesis_prompt
# ---------------------------------------------------------------------------

class TestBuildSynthesisPrompt:

    def test_includes_all_findings(self):
        findings = [
            {"title": "Finding A", "content": "Content A"},
            {"title": "Finding B", "content": "Content B"},
        ]
        system, user = PromptBuilder.build_synthesis_prompt("Objective", findings)
        assert "Finding A" in user
        assert "Finding B" in user
        assert "Content A" in user

    def test_includes_objective(self):
        _, user = PromptBuilder.build_synthesis_prompt("My Objective", [])
        assert "My Objective" in user

    def test_build_synthesis_prompt_includes_findings(self):
        """All provided findings should appear in the user prompt."""
        findings_list = [
            {"title": "Finding A", "content": "Content A"},
            {"title": "Finding B", "content": "Content B"},
        ]
        system, user = PromptBuilder.build_synthesis_prompt(
            objective_title="Objective X",
            findings=findings_list,
        )
        assert "Objective X" in user
        assert "Content A" in user
        assert "Content B" in user
        assert "Systems Synthesizer" in system

    def test_build_synthesis_prompt_empty_findings(self):
        """Empty findings list should still produce valid prompts."""
        system, user = PromptBuilder.build_synthesis_prompt(
            objective_title="Objective X",
            findings=[],
        )
        assert "Objective X" in user
        assert isinstance(system, str)

    def test_build_synthesis_prompt_finding_numbering(self):
        """Findings should be numbered sequentially."""
        findings_list = [
            {"title": "F1", "content": "C1"},
            {"title": "F2", "content": "C2"},
            {"title": "F3", "content": "C3"},
        ]
        _, user = PromptBuilder.build_synthesis_prompt("Obj", findings=findings_list)
        assert "Finding 1: F1" in user
        assert "Finding 2: F2" in user
        assert "Finding 3: F3" in user

    def test_build_synthesis_prompt_untitled_finding(self):
        """A finding without a 'title' key should show 'Untitled'."""
        findings_list = [{"content": "Some content"}]
        _, user = PromptBuilder.build_synthesis_prompt("Obj", findings=findings_list)
        assert "Untitled" in user


# ---------------------------------------------------------------------------
# build_dream_cycle_prompt
# ---------------------------------------------------------------------------

class TestBuildDreamCyclePrompt:

    def test_includes_kg_summary(self):
        system, user = PromptBuilder.build_dream_cycle_prompt(
            recent_kg_summary="Recent nodes summary",
            kg_stats={"node_count": 100, "edge_count": 50, "avg_confidence": 0.75},
        )
        assert "Recent nodes summary" in user
        assert "100" in user

    def test_includes_stats(self):
        _, user = PromptBuilder.build_dream_cycle_prompt(
            recent_kg_summary="summary",
            kg_stats={"node_count": 42, "edge_count": 10, "avg_confidence": 0.5},
        )
        assert "42" in user

    def test_build_dream_cycle_prompt_includes_stats(self):
        """Dream cycle prompt should include KG statistics."""
        system, user = PromptBuilder.build_dream_cycle_prompt(
            recent_kg_summary="3 new nodes about protein folding",
            kg_stats={
                "node_count": 150,
                "edge_count": 300,
                "avg_confidence": 0.78,
            },
        )
        assert "3 new nodes about protein folding" in user
        assert "150" in user
        assert "300" in user
        assert "0.780" in user
        assert "Nightwatch Consolidator" in system

    def test_build_dream_cycle_prompt_missing_stats_default_to_zero(self):
        """Missing stats keys should default to 0."""
        _, user = PromptBuilder.build_dream_cycle_prompt(
            recent_kg_summary="summary",
            kg_stats={},
        )
        # node_count defaults to 0, edge_count defaults to 0, avg_confidence defaults to 0
        assert "Total nodes: 0" in user
        assert "Total edges: 0" in user

    def test_build_dream_cycle_prompt_has_json_schema(self):
        _, user = PromptBuilder.build_dream_cycle_prompt(
            recent_kg_summary="summary",
            kg_stats={"node_count": 10, "edge_count": 20, "avg_confidence": 0.5},
        )
        assert '"patterns_identified"' in user
        assert '"proposed_objectives"' in user
        assert '"contradictions_found"' in user


# ---------------------------------------------------------------------------
# build_mutation_prompt
# ---------------------------------------------------------------------------

class TestBuildMutationPrompt:

    def test_includes_current_prompt(self):
        system, user = PromptBuilder.build_mutation_prompt(
            current_prompt="You are a researcher",
            performance_summary="Good performance",
        )
        assert "You are a researcher" in user

    def test_includes_performance(self):
        _, user = PromptBuilder.build_mutation_prompt("prompt", "Score: 0.85")
        assert "0.85" in user

    def test_includes_mutation_type(self):
        _, user = PromptBuilder.build_mutation_prompt("p", "s", mutation_type="role_expansion")
        assert "role_expansion" in user

    def test_build_mutation_prompt_includes_performance(self):
        """Mutation prompt should include the current prompt and performance summary."""
        system, user = PromptBuilder.build_mutation_prompt(
            current_prompt="You are a researcher focused on biology.",
            performance_summary="Acceptance rate: 60%, avg review: 0.7",
        )
        assert "You are a researcher focused on biology." in user
        assert "Acceptance rate: 60%" in user
        assert "evolutionary engineer" in system.lower()

    def test_build_mutation_prompt_default_mutation_type(self):
        _, user = PromptBuilder.build_mutation_prompt(
            current_prompt="Prompt",
            performance_summary="Summary",
        )
        assert "prompt_edit" in user

    def test_build_mutation_prompt_has_json_schema(self):
        _, user = PromptBuilder.build_mutation_prompt("Prompt", "Summary")
        assert '"mutated_prompt"' in user
        assert '"changes_description"' in user
        assert '"expected_improvement"' in user


# ---------------------------------------------------------------------------
# build_market_action_prompt
# ---------------------------------------------------------------------------

class TestBuildMarketActionPrompt:

    def test_build_market_action_prompt_includes_core_context(self):
        system, user = PromptBuilder.build_market_action_prompt(
            persona_name="Red Team Trader",
            objective_title="Securities Exchange",
            action_type="place_order",
            action_context="Bid on an objective note using excess credits.",
        )

        assert "autonomous market participant" in system
        assert "Red Team Trader" in user
        assert "Securities Exchange" in user
        assert "place_order" in user
        assert "excess credits" in user

    def test_build_market_action_prompt_has_machine_valid_schema(self):
        _, user = PromptBuilder.build_market_action_prompt(
            persona_name="Scout Seller",
            objective_title="Marketplace Operations",
            action_type="craft_listing",
            action_context="List a bounded scout package.",
        )

        assert '"action_type"' in user
        assert '"template_code"' in user
        assert '"listing_kind"' in user
        assert '"instrument_symbol"' in user
        assert '"side"' in user
        assert '"price"' in user
        assert '"quantity"' in user
        assert '"details"' in user


# ---------------------------------------------------------------------------
# build_file_context_section (Phase 2-7 file upload support)
# ---------------------------------------------------------------------------

class TestBuildFileContextSection:
    """Verify build_file_context_section() formats attachment contexts for prompts."""

    def _make_context(
        self,
        text: str | None = None,
        image_path: Path | None = None,
        filename: str = "test.txt",
        content_type: str = "text/plain",
        size_bytes: int = 1024,
    ) -> AttachmentContext:
        return AttachmentContext(
            attachment_id=uuid4(),
            filename=filename,
            content_type=content_type,
            size_bytes=size_bytes,
            text_content=text,
            image_path=image_path,
        )

    def test_text_contexts_returns_formatted_section(self):
        """Contexts with text_content produce a formatted '## Research Context Files' section."""
        ctx1 = self._make_context(
            text="Gene expression data for BRCA1.",
            filename="brca1_data.csv",
            content_type="text/csv",
            size_bytes=2048,
        )
        ctx2 = self._make_context(
            text="Clinical trial results summary.",
            filename="trial_results.txt",
            content_type="text/plain",
            size_bytes=4096,
        )

        result = PromptBuilder.build_file_context_section([ctx1, ctx2])

        assert result.startswith("## Research Context Files")
        assert "brca1_data.csv" in result
        assert "Gene expression data for BRCA1." in result
        assert "trial_results.txt" in result
        assert "Clinical trial results summary." in result
        # Size should be formatted in KB
        assert "2 KB" in result
        assert "4 KB" in result

    def test_single_text_context_returns_formatted_section(self):
        """A single text context produces a valid section."""
        ctx = self._make_context(
            text="Some important research data.",
            filename="research.csv",
            content_type="text/csv",
            size_bytes=512,
        )

        result = PromptBuilder.build_file_context_section([ctx])

        assert "## Research Context Files" in result
        assert "research.csv" in result
        assert "Some important research data." in result

    def test_empty_contexts_returns_empty_string(self):
        """An empty list of contexts returns an empty string."""
        result = PromptBuilder.build_file_context_section([])
        assert result == ""

    def test_only_image_contexts_returns_empty_string(self):
        """Contexts with only image_path and no text return empty string."""
        ctx1 = self._make_context(
            image_path=Path("/uploads/diagram.png"),
            filename="diagram.png",
            content_type="image/png",
        )
        ctx2 = self._make_context(
            image_path=Path("/uploads/photo.jpg"),
            filename="photo.jpg",
            content_type="image/jpeg",
        )

        result = PromptBuilder.build_file_context_section([ctx1, ctx2])

        assert result == ""

    def test_mixed_text_and_image_only_includes_text(self):
        """When mixing text and image contexts, only text ones appear in section."""
        text_ctx = self._make_context(
            text="CSV data content",
            filename="data.csv",
            content_type="text/csv",
            size_bytes=1024,
        )
        image_ctx = self._make_context(
            image_path=Path("/uploads/chart.png"),
            filename="chart.png",
            content_type="image/png",
        )

        result = PromptBuilder.build_file_context_section([text_ctx, image_ctx])

        assert "data.csv" in result
        assert "chart.png" not in result

    def test_contexts_with_none_text_are_skipped(self):
        """Contexts with text_content=None are skipped."""
        ctx_none = self._make_context(text=None, filename="empty.txt")
        ctx_text = self._make_context(
            text="Actual content",
            filename="real.txt",
            size_bytes=512,
        )

        result = PromptBuilder.build_file_context_section([ctx_none, ctx_text])

        assert "real.txt" in result
        assert "empty.txt" not in result

    def test_contexts_with_empty_string_text_are_skipped(self):
        """Contexts with text_content='' are treated as falsy and skipped."""
        ctx = self._make_context(text="", filename="blank.txt")

        result = PromptBuilder.build_file_context_section([ctx])

        assert result == ""

    def test_section_contains_separator(self):
        """Multiple text files are separated by a horizontal rule."""
        ctx1 = self._make_context(text="File 1 content", filename="a.txt", size_bytes=100)
        ctx2 = self._make_context(text="File 2 content", filename="b.txt", size_bytes=200)

        result = PromptBuilder.build_file_context_section([ctx1, ctx2])

        assert "---" in result


# ---------------------------------------------------------------------------
# build_decomposition_prompt with file_context (Phase 2-7 file upload support)
# ---------------------------------------------------------------------------

class TestBuildDecompositionPromptWithFileContext:
    """Verify build_decomposition_prompt() handles the file_context parameter."""

    def test_with_file_context_includes_section_in_user_prompt(self):
        """When file_context is provided, it appears in the user prompt."""
        file_section = "## Research Context Files\n\n### File: genes.csv\nBRCA1, TP53, EGFR"

        system, user = PromptBuilder.build_decomposition_prompt(
            objective_title="Analyze gene interactions",
            objective_description="Investigate BRCA1 interactions",
            file_context=file_section,
        )

        assert "Research Context Files" in user
        assert "BRCA1, TP53, EGFR" in user
        assert "genes.csv" in user

    def test_with_file_context_includes_instruction(self):
        """When file_context is provided, the IMPORTANT instruction appears."""
        system, user = PromptBuilder.build_decomposition_prompt(
            objective_title="Title",
            objective_description="Desc",
            file_context="## Research Context Files\n\nSome data here",
        )

        assert "IMPORTANT" in user
        assert "context files" in user.lower()

    def test_without_file_context_works_normally(self):
        """When file_context is not provided, prompt works as before (backward compat)."""
        system, user = PromptBuilder.build_decomposition_prompt(
            objective_title="Title",
            objective_description="Description",
        )

        assert "Title" in user
        assert "Description" in user
        assert "IMPORTANT" not in user
        # Should not contain any file context section indicators
        assert "Research Context Files" not in user

    def test_empty_file_context_treated_as_no_context(self):
        """Empty string file_context is treated as no context (backward compat)."""
        system, user = PromptBuilder.build_decomposition_prompt(
            objective_title="Title",
            objective_description="Desc",
            file_context="",
        )

        assert "IMPORTANT" not in user
        assert "Research Context Files" not in user

    def test_file_context_does_not_affect_system_prompt(self):
        """file_context only affects the user prompt, not the system prompt."""
        system_with, user_with = PromptBuilder.build_decomposition_prompt(
            objective_title="T",
            objective_description="D",
            file_context="## Research Context Files\n\nData",
        )
        system_without, user_without = PromptBuilder.build_decomposition_prompt(
            objective_title="T",
            objective_description="D",
        )

        assert system_with == system_without

    def test_system_prompt_mentions_research_context_files_rule(self):
        """System prompt should instruct the model to use research context files."""
        system, _ = PromptBuilder.build_decomposition_prompt(
            objective_title="T",
            objective_description="D",
        )

        assert "context files" in system.lower()
