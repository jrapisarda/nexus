"""Unit tests for nexus_core.llm.response_parser — ResponseParser and data classes."""

import json

import pytest

from nexus_core.llm.response_parser import (
    ChallengeData,
    DecompositionData,
    DreamCycleData,
    FindingData,
    FindingContractError,
    KGExtractionData,
    MarketActionData,
    MutationData,
    ResponseParser,
    ReviewData,
    StructuredOutputError,
    SubObjectiveData,
    SynthesisData,
)


# ---------------------------------------------------------------------------
# _extract_json
# ---------------------------------------------------------------------------

class TestExtractJson:

    def test_plain_json(self):
        result = ResponseParser._extract_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_markdown_code_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = ResponseParser._extract_json(text)
        assert result == {"key": "value"}

    def test_json_in_text(self):
        text = 'Here is my response: {"title": "test"} and more text'
        result = ResponseParser._extract_json(text)
        assert result is not None
        assert result.get("title") == "test"

    def test_invalid_json_returns_none(self):
        result = ResponseParser._extract_json("not json at all")
        assert result is None

    def test_empty_string(self):
        result = ResponseParser._extract_json("")
        assert result is None

    def test_json_array(self):
        result = ResponseParser._extract_json('[{"a": 1}, {"b": 2}]')
        assert isinstance(result, list)
        assert len(result) == 2

    def test_extract_json_from_plain_text(self):
        """Should return None for text with no JSON at all."""
        result = ResponseParser._extract_json(
            "This is purely natural language with no structured data."
        )
        assert result is None

    def test_extract_json_from_generic_code_block(self):
        """Should handle ``` blocks without the json language tag."""
        text = '```\n{"status": "ok"}\n```'
        result = ResponseParser._extract_json(text)
        assert result == {"status": "ok"}

    def test_extract_json_with_surrounding_whitespace(self):
        text = '   \n  {"a": 1}  \n  '
        result = ResponseParser._extract_json(text)
        assert result == {"a": 1}

    def test_extract_nested_json(self):
        text = json.dumps({"outer": {"inner": "value"}})
        result = ResponseParser._extract_json(text)
        assert result == {"outer": {"inner": "value"}}

    def test_extract_json_from_unclosed_fence_if_payload_is_complete(self):
        text = '```json\n{"key": "value"}'
        result = ResponseParser._extract_json(text)
        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# parse_finding
# ---------------------------------------------------------------------------

class TestParseFinding:

    def test_parse_finding_from_json(self):
        content = json.dumps({
            "title": "Test Finding",
            "content": "Finding content",
            "confidence": 0.8,
            "citations": [{"title": "Source A", "url": "https://example.com"}],
            "kg_entities": [{"label": "Entity1", "type": "concept"}],
            "kg_relationships": [],
        })
        result = ResponseParser.parse_finding(content)
        assert isinstance(result, FindingData)
        assert result.title == "Test Finding"
        assert result.confidence == 0.8
        assert result.citations[0]["title"] == "Source A"
        assert len(result.kg_entities) == 1

    def test_parse_finding_from_markdown_code_block(self):
        content = '```json\n{"title": "Wrapped", "content": "data", "confidence": 0.9}\n```'
        result = ResponseParser.parse_finding(content)
        assert result.title == "Wrapped"
        assert result.content == "data"
        assert result.confidence == 0.9

    def test_parse_finding_fallback_on_invalid_json(self):
        raw_text = "Just some plain text analysis without any JSON"
        result = ResponseParser.parse_finding(raw_text)
        assert isinstance(result, FindingData)
        assert result.title == "Untitled Finding"
        assert result.content == raw_text
        assert result.confidence == 0.5

    def test_parse_finding_defaults(self):
        """Missing fields should use defaults."""
        content = json.dumps({"title": "Minimal"})
        result = ResponseParser.parse_finding(content)
        assert result.title == "Minimal"
        assert result.confidence == 0.5
        assert result.kg_entities == []
        assert result.kg_relationships == []
        assert result.citations == []

    def test_parse_finding_from_list(self):
        """If JSON is a list, the first element should be used."""
        content = json.dumps([
            {"title": "First", "content": "C1"},
            {"title": "Second", "content": "C2"},
        ])
        result = ResponseParser.parse_finding(content)
        assert result.title == "First"

    def test_parse_finding_strict_raises_on_invalid_json(self):
        with pytest.raises(StructuredOutputError):
            ResponseParser.parse_finding("plain text only", strict=True)


class TestParseResearchFinding:
    def _valid_payload(self, **overrides):
        payload = {
            "title": "Validated research finding",
            "content": "Detailed markdown content.",
            "confidence": 0.82,
            "citations": [
                {
                    "title": "Source title",
                    "source_type": "paper",
                    "source_name": "Nature",
                    "url": "https://example.com/paper",
                    "doi": "",
                    "published_date": "2026-03-19",
                    "authors": ["Author A"],
                    "supporting_snippet": "A direct supporting passage.",
                }
            ],
            "kg_contribution": {
                "entities": [
                    {"label": "Drug X", "type": "concept", "properties": {}},
                    {"label": "Disease Y", "type": "concept", "properties": {}},
                ],
                "relationships": [
                    {
                        "source": "Drug X",
                        "target": "Disease Y",
                        "type": "treats",
                        "weight": 0.72,
                    }
                ],
            },
        }
        payload.update(overrides)
        return payload

    def test_parse_research_finding_valid(self):
        result = ResponseParser.parse_research_finding(
            json.dumps(self._valid_payload())
        )
        assert result.title == "Validated research finding"
        assert result.citations[0]["source_name"] == "Nature"
        assert result.kg_entities[0]["label"] == "Drug X"
        assert result.kg_relationships[0]["type"] == "treats"

    def test_parse_research_finding_accepts_specific_snake_case_relationships(self):
        payload = self._valid_payload(
            kg_contribution={
                "entities": [
                    {"label": "Claude Code", "type": "entity", "properties": {}},
                    {"label": "GitHub Copilot", "type": "entity", "properties": {}},
                ],
                "relationships": [
                    {
                        "source": "Claude Code",
                        "target": "GitHub Copilot",
                        "type": "competes_with",
                        "weight": 0.61,
                    }
                ],
            }
        )

        result = ResponseParser.parse_research_finding(json.dumps(payload))

        assert result.kg_relationships[0]["type"] == "competes_with"

    def test_parse_research_finding_requires_citations_key(self):
        payload = self._valid_payload()
        payload.pop("citations")
        with pytest.raises(FindingContractError, match="citations key"):
            ResponseParser.parse_research_finding(json.dumps(payload))

    def test_parse_research_finding_rejects_malformed_citation(self):
        payload = self._valid_payload(
            citations=[
                {
                    "title": "Source title",
                    "source_type": "paper",
                    "source_name": "",
                    "url": "",
                    "doi": "",
                    "published_date": "",
                    "authors": [],
                    "supporting_snippet": "A supporting passage.",
                }
            ]
        )
        with pytest.raises(FindingContractError, match="source_name|url or doi"):
            ResponseParser.parse_research_finding(json.dumps(payload))

    def test_parse_research_finding_requires_kg_contribution(self):
        payload = self._valid_payload()
        payload.pop("kg_contribution")
        with pytest.raises(FindingContractError, match="kg_contribution object"):
            ResponseParser.parse_research_finding(json.dumps(payload))

    def test_parse_research_finding_requires_non_empty_entities(self):
        payload = self._valid_payload(
            kg_contribution={"entities": [], "relationships": []}
        )
        with pytest.raises(FindingContractError, match="entities must be a non-empty array"):
            ResponseParser.parse_research_finding(json.dumps(payload))

    def test_parse_research_finding_rejects_relationships_with_unknown_labels(self):
        payload = self._valid_payload(
            kg_contribution={
                "entities": [{"label": "Drug X", "type": "concept", "properties": {}}],
                "relationships": [
                    {
                        "source": "Drug X",
                        "target": "Disease Y",
                        "type": "treats",
                        "weight": 0.72,
                    }
                ],
            }
        )
        with pytest.raises(FindingContractError, match="reference labels declared"):
            ResponseParser.parse_research_finding(json.dumps(payload))


# ---------------------------------------------------------------------------
# parse_findings (multiple)
# ---------------------------------------------------------------------------

class TestParseFindings:

    def test_single_finding(self):
        content = json.dumps({"title": "One", "content": "Data"})
        result = ResponseParser.parse_findings(content)
        assert len(result) == 1
        assert result[0].title == "One"

    def test_multiple_findings(self):
        content = json.dumps([
            {"title": "First", "content": "A"},
            {"title": "Second", "content": "B"},
        ])
        result = ResponseParser.parse_findings(content)
        assert len(result) == 2

    def test_wrapped_in_findings_key(self):
        content = json.dumps({
            "findings": [
                {"title": "F1", "content": "C1"},
                {"title": "F2", "content": "C2"},
            ]
        })
        result = ResponseParser.parse_findings(content)
        assert len(result) == 2

    def test_invalid_json_fallback(self):
        result = ResponseParser.parse_findings("no json here")
        assert len(result) == 1
        assert result[0].title == "Untitled Finding"


# ---------------------------------------------------------------------------
# parse_review
# ---------------------------------------------------------------------------

class TestParseReview:

    def test_parse_review_valid_json(self):
        content = json.dumps({
            "methodology_critique": "Good methodology",
            "evidence_evaluation": "Strong evidence",
            "novelty_assessment": "Novel contribution",
            "confidence_rating": 0.85,
            "verdict": "approve",
            "revision_feedback": None,
        })
        result = ResponseParser.parse_review(content)
        assert isinstance(result, ReviewData)
        assert result.verdict == "approve"
        assert result.confidence_rating == 0.85
        assert result.methodology_critique == "Good methodology"
        assert result.revision_feedback is None

    def test_parse_review_fallback(self):
        """Invalid JSON should return a reject review with 0.0 confidence."""
        result = ResponseParser.parse_review("invalid review text")
        assert isinstance(result, ReviewData)
        assert result.verdict == "reject"
        assert result.confidence_rating == 0.0
        assert "Unable to parse" in result.methodology_critique

    def test_parse_review_revise_verdict(self):
        content = json.dumps({
            "methodology_critique": "Needs improvement",
            "evidence_evaluation": "Weak evidence",
            "novelty_assessment": "Incremental",
            "confidence_rating": 0.4,
            "verdict": "revise",
            "revision_feedback": "Add more data sources",
        })
        result = ResponseParser.parse_review(content)
        assert result.verdict == "revise"
        assert result.revision_feedback == "Add more data sources"

    def test_parse_review_missing_fields_use_defaults(self):
        content = json.dumps({"verdict": "approve"})
        result = ResponseParser.parse_review(content)
        assert result.verdict == "approve"
        assert result.methodology_critique == ""
        assert result.confidence_rating == 0.0

    def test_parse_review_strict_raises_on_invalid_json(self):
        with pytest.raises(StructuredOutputError):
            ResponseParser.parse_review("not structured", strict=True)

    def test_parse_review_strict_raises_on_missing_required_fields(self):
        content = json.dumps({"verdict": "approve"})
        with pytest.raises(StructuredOutputError):
            ResponseParser.parse_review(content, strict=True)


# ---------------------------------------------------------------------------
# parse_decomposition
# ---------------------------------------------------------------------------

class TestParseDecomposition:

    def test_parse_decomposition_with_sub_objectives(self):
        content = json.dumps({
            "sub_objectives": [
                {
                    "id": "sub_1",
                    "title": "Research AI Impact",
                    "description": "Analyze AI automation effects",
                    "role_class": "researcher",
                    "dependency_type": "parallel",
                    "depends_on": [],
                    "impact_level": "high-impact",
                    "rationale": "Foundation research",
                },
                {
                    "id": "sub_2",
                    "title": "Synthesize Solutions",
                    "description": "Combine findings",
                    "role_class": "synthesizer",
                    "dependency_type": "sequential",
                    "depends_on": ["sub_1"],
                    "impact_level": "routine",
                    "rationale": "Integration needed",
                },
            ]
        })
        result = ResponseParser.parse_decomposition(content)
        assert isinstance(result, DecompositionData)
        assert len(result.sub_objectives) == 2
        assert result.sub_objectives[0].id == "sub_1"
        assert result.sub_objectives[0].role_class == "researcher"
        assert result.sub_objectives[1].depends_on == ["sub_1"]
        assert result.sub_objectives[1].dependency_type == "sequential"

    def test_empty_decomposition(self):
        result = ResponseParser.parse_decomposition("not json")
        assert isinstance(result, DecompositionData)
        assert len(result.sub_objectives) == 0

    def test_parse_decomposition_from_list(self):
        """If the JSON is a direct list of sub-objectives, parse them directly."""
        content = json.dumps([
            {"id": "s1", "title": "T1", "description": "D1",
             "role_class": "researcher", "dependency_type": "parallel"},
        ])
        result = ResponseParser.parse_decomposition(content)
        assert len(result.sub_objectives) == 1
        assert result.sub_objectives[0].id == "s1"

    def test_parse_decomposition_default_fields(self):
        """Missing optional fields should use defaults."""
        content = json.dumps({
            "sub_objectives": [{"id": "s1", "title": "T", "description": "D"}]
        })
        result = ResponseParser.parse_decomposition(content)
        sub = result.sub_objectives[0]
        assert sub.role_class == "researcher"
        assert sub.dependency_type == "parallel"
        assert sub.impact_level == "routine"
        assert sub.depends_on == []


# ---------------------------------------------------------------------------
# parse_challenge
# ---------------------------------------------------------------------------

class TestParseChallenge:

    def test_parse_challenge_with_flaw(self):
        content = json.dumps({
            "has_flaw": True,
            "flaw_type": "logical",
            "description": "Circular reasoning detected",
            "counter_evidence": "The premise assumes the conclusion",
            "severity": "major",
            "confidence": 0.9,
        })
        result = ResponseParser.parse_challenge(content)
        assert isinstance(result, ChallengeData)
        assert result.has_flaw is True
        assert result.flaw_type == "logical"
        assert result.description == "Circular reasoning detected"
        assert result.counter_evidence == "The premise assumes the conclusion"
        assert result.severity == "major"
        assert result.confidence == 0.9

    def test_parse_challenge_no_flaw(self):
        content = json.dumps({"has_flaw": False, "confidence": 0.3})
        result = ResponseParser.parse_challenge(content)
        assert result.has_flaw is False
        assert result.flaw_type is None
        assert result.description is None
        assert result.severity is None
        assert result.confidence == 0.3

    def test_parse_challenge_fallback_on_garbage(self):
        result = ResponseParser.parse_challenge("garbage text")
        assert isinstance(result, ChallengeData)
        assert result.has_flaw is False
        assert result.confidence == 0.5

    def test_parse_challenge_from_list(self):
        """If JSON is a list, first element should be used."""
        content = json.dumps([
            {"has_flaw": True, "flaw_type": "evidential", "confidence": 0.7},
        ])
        result = ResponseParser.parse_challenge(content)
        assert result.has_flaw is True
        assert result.flaw_type == "evidential"


# ---------------------------------------------------------------------------
# parse_mutation
# ---------------------------------------------------------------------------

class TestParseMutation:

    def test_parse_mutation(self):
        content = json.dumps({
            "mutated_prompt": "New improved prompt",
            "changes_description": "Added specificity",
            "expected_improvement": "Better focus",
        })
        result = ResponseParser.parse_mutation(content)
        assert isinstance(result, MutationData)
        assert result.mutated_prompt == "New improved prompt"
        assert result.changes_description == "Added specificity"
        assert result.expected_improvement == "Better focus"

    def test_parse_mutation_fallback(self):
        result = ResponseParser.parse_mutation("bad data")
        assert isinstance(result, MutationData)
        assert result.mutated_prompt == ""
        assert "Failed to parse" in result.changes_description
        assert result.expected_improvement == ""

    def test_parse_mutation_from_markdown(self):
        content = '```json\n{"mutated_prompt": "MP", "changes_description": "CD", "expected_improvement": "EI"}\n```'
        result = ResponseParser.parse_mutation(content)
        assert result.mutated_prompt == "MP"


# ---------------------------------------------------------------------------
# parse_dream_cycle
# ---------------------------------------------------------------------------

class TestParseDreamCycle:

    def test_valid_dream_cycle(self):
        content = json.dumps({
            "patterns_identified": [{"description": "Pattern A", "confidence": 0.8}],
            "proposed_objectives": [{"title": "New Research", "description": "Investigate X"}],
            "contradictions_found": [{"description": "A contradicts B"}],
        })
        result = ResponseParser.parse_dream_cycle(content)
        assert isinstance(result, DreamCycleData)
        assert len(result.patterns_identified) == 1
        assert len(result.proposed_objectives) == 1
        assert len(result.contradictions_found) == 1

    def test_dream_cycle_fallback(self):
        result = ResponseParser.parse_dream_cycle("not json")
        assert isinstance(result, DreamCycleData)
        assert result.patterns_identified == []
        assert result.proposed_objectives == []
        assert result.contradictions_found == []

    def test_dream_cycle_partial_data(self):
        """Missing keys should default to empty lists."""
        content = json.dumps({"patterns_identified": [{"description": "P1"}]})
        result = ResponseParser.parse_dream_cycle(content)
        assert len(result.patterns_identified) == 1
        assert result.proposed_objectives == []
        assert result.contradictions_found == []


# ---------------------------------------------------------------------------
# parse_synthesis
# ---------------------------------------------------------------------------

class TestParseSynthesis:

    def test_returns_raw_content(self):
        result = ResponseParser.parse_synthesis("# Full Markdown Report\n\nContent here.")
        assert isinstance(result, SynthesisData)
        assert "Full Markdown Report" in result.content

    def test_empty_content(self):
        result = ResponseParser.parse_synthesis("")
        assert isinstance(result, SynthesisData)
        assert result.content == ""

    def test_preserves_markdown_formatting(self):
        md = "## Section\n\n- Item 1\n- Item 2\n\n**Bold** text"
        result = ResponseParser.parse_synthesis(md)
        assert result.content == md


# ---------------------------------------------------------------------------
# parse_market_action
# ---------------------------------------------------------------------------

class TestParseMarketAction:

    def test_parse_market_action_valid_listing_payload(self):
        content = json.dumps(
            {
                "action_type": "craft_listing",
                "persona_id": "persona-1",
                "template_code": "memory_digest",
                "listing_kind": "soft_good",
                "price": 12.5,
                "quantity": 1,
                "details": {"listing_id": "listing-1"},
            }
        )

        result = ResponseParser.parse_market_action(content, strict=True)

        assert isinstance(result, MarketActionData)
        assert result.action_type == "craft_listing"
        assert result.template_code == "memory_digest"
        assert result.listing_kind == "soft_good"
        assert result.price == 12.5
        assert result.quantity == 1
        assert result.details["listing_id"] == "listing-1"

    def test_parse_market_action_valid_order_payload(self):
        content = json.dumps(
            {
                "action_type": "place_order",
                "persona_id": "persona-1",
                "instrument_symbol": "OBJ-ABC123",
                "side": "buy",
                "price": 51.0,
                "quantity": 2.0,
                "details": {"order_id": "order-1"},
            }
        )

        result = ResponseParser.parse_market_action(content, strict=True)

        assert result.action_type == "place_order"
        assert result.instrument_symbol == "OBJ-ABC123"
        assert result.side == "buy"
        assert result.price == 51.0
        assert result.quantity == 2.0

    def test_parse_market_action_strict_requires_action_type(self):
        with pytest.raises(StructuredOutputError, match="action_type"):
            ResponseParser.parse_market_action(json.dumps({"price": 12}), strict=True)

    def test_parse_market_action_strict_requires_listing_kind_for_listing_actions(self):
        with pytest.raises(StructuredOutputError, match="listing_kind"):
            ResponseParser.parse_market_action(
                json.dumps({"action_type": "craft_listing"}),
                strict=True,
            )

    def test_parse_market_action_strict_requires_side_and_symbol_for_orders(self):
        with pytest.raises(StructuredOutputError, match="side"):
            ResponseParser.parse_market_action(
                json.dumps({"action_type": "place_order", "instrument_symbol": "OBJ-1"}),
                strict=True,
            )

        with pytest.raises(StructuredOutputError, match="instrument_symbol"):
            ResponseParser.parse_market_action(
                json.dumps({"action_type": "place_order", "side": "buy"}),
                strict=True,
            )

    def test_parse_market_action_strict_requires_positive_price_and_quantity(self):
        with pytest.raises(StructuredOutputError, match="price"):
            ResponseParser.parse_market_action(
                json.dumps({"action_type": "place_order", "side": "buy", "instrument_symbol": "OBJ-1", "price": 0}),
                strict=True,
            )

        with pytest.raises(StructuredOutputError, match="quantity"):
            ResponseParser.parse_market_action(
                json.dumps({"action_type": "place_order", "side": "buy", "instrument_symbol": "OBJ-1", "quantity": -1}),
                strict=True,
            )


# ---------------------------------------------------------------------------
# parse_kg_extraction
# ---------------------------------------------------------------------------

class TestParseKGExtraction:

    def test_with_kg_entities_key(self):
        content = json.dumps({
            "kg_entities": [{"label": "Drug X", "type": "concept"}],
            "kg_relationships": [{"source": "Drug X", "target": "Disease Y", "type": "treats"}],
        })
        result = ResponseParser.parse_kg_extraction(content)
        assert isinstance(result, KGExtractionData)
        assert len(result.entities) == 1
        assert len(result.relationships) == 1

    def test_with_entities_key(self):
        """Should also accept 'entities' and 'relationships' keys."""
        content = json.dumps({
            "entities": [{"label": "A"}],
            "relationships": [{"source": "A", "target": "B"}],
        })
        result = ResponseParser.parse_kg_extraction(content)
        assert len(result.entities) == 1
        assert len(result.relationships) == 1

    def test_fallback_on_invalid(self):
        result = ResponseParser.parse_kg_extraction("no json")
        assert isinstance(result, KGExtractionData)
        assert result.entities == []
        assert result.relationships == []


# ---------------------------------------------------------------------------
# Dataclass field verification
# ---------------------------------------------------------------------------

class TestDataclassFields:

    def test_finding_data_defaults(self):
        f = FindingData(title="T", content="C")
        assert f.confidence == 0.5
        assert f.kg_entities == []
        assert f.kg_relationships == []
        assert f.citations == []

    def test_sub_objective_data_defaults(self):
        s = SubObjectiveData(
            id="s1", title="T", description="D",
            role_class="researcher", dependency_type="parallel",
        )
        assert s.depends_on == []
        assert s.impact_level == "routine"
        assert s.rationale == ""

    def test_challenge_data_defaults(self):
        c = ChallengeData(has_flaw=False)
        assert c.flaw_type is None
        assert c.description is None
        assert c.confidence == 0.5
