import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

logger = structlog.get_logger(__name__)


class StructuredOutputError(ValueError):
    """Raised when a model response should contain strict JSON but does not."""


class FindingContractError(StructuredOutputError):
    """Raised when a research finding violates the structured evidence contract."""


@dataclass
class FindingData:
    """Parsed finding from agent output."""
    title: str
    content: str
    confidence: float = 0.5
    kg_entities: list[dict] = field(default_factory=list)
    kg_relationships: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)


@dataclass
class ReviewData:
    """Parsed peer review assessment."""
    methodology_critique: str
    evidence_evaluation: str
    novelty_assessment: str
    confidence_rating: float
    verdict: str  # approve, reject, revise
    revision_feedback: Optional[str] = None


@dataclass
class SubObjectiveData:
    """Parsed sub-objective from decomposition."""
    id: str
    title: str
    description: str
    role_class: str
    dependency_type: str  # parallel, sequential, conditional
    depends_on: list[str] = field(default_factory=list)
    impact_level: str = "routine"
    rationale: str = ""


@dataclass
class ChallengeData:
    """Parsed Red Team challenge."""
    has_flaw: bool
    flaw_type: Optional[str] = None
    description: Optional[str] = None
    counter_evidence: Optional[str] = None
    severity: Optional[str] = None
    confidence: float = 0.5


@dataclass
class KGExtractionData:
    """Parsed KG entities and relationships from agent output."""
    entities: list[dict] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)


@dataclass
class DecompositionData:
    """Parsed objective decomposition result."""
    sub_objectives: list[SubObjectiveData] = field(default_factory=list)


@dataclass
class MutationData:
    """Parsed mutation proposal."""
    mutated_prompt: str
    changes_description: str
    expected_improvement: str


@dataclass
class DreamCycleData:
    """Parsed Dream Cycle consolidation result."""
    patterns_identified: list[dict] = field(default_factory=list)
    proposed_objectives: list[dict] = field(default_factory=list)
    contradictions_found: list[dict] = field(default_factory=list)


@dataclass
class SynthesisData:
    """Parsed synthesis output."""
    content: str


@dataclass
class MarketActionData:
    """Parsed marketplace or securities action."""
    action_type: str
    persona_id: str | None = None
    template_code: str | None = None
    listing_id: str | None = None
    listing_kind: str | None = None
    instrument_symbol: str | None = None
    side: str | None = None
    price: float | None = None
    quantity: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


class ResponseParser:
    """Parses structured JSON from Kimi K2.5 responses."""

    RELATIONSHIP_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,99}$")
    REQUIRED_CITATION_KEYS = {
        "title",
        "source_type",
        "source_name",
        "url",
        "doi",
        "published_date",
        "authors",
        "supporting_snippet",
    }
    @staticmethod
    def _extract_json(text: str) -> dict | list | None:
        """Extract JSON from text that may contain markdown code blocks."""
        text = text.strip()
        if not text:
            logger.warning("failed_to_extract_json", reason="empty_response", text_preview="")
            return None

        # Try direct parse first.
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            last_error = exc

        # Handle responses that start with a markdown fence but never close it.
        fence_match = re.match(r"^```(?:json)?\s*\n?(.*)$", text, re.DOTALL)
        if fence_match:
            fenced_payload = fence_match.group(1).strip()
            if fenced_payload.endswith("```"):
                fenced_payload = fenced_payload[:-3].rstrip()
            try:
                return json.loads(fenced_payload)
            except json.JSONDecodeError as exc:
                last_error = exc

        # Try extracting from markdown code blocks.
        patterns = [
            r'```json\s*\n?(.*?)\n?\s*```',
            r'```\s*\n?(.*?)\n?\s*```',
            r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}',  # Match outermost braces
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.DOTALL)
            for match in matches:
                try:
                    return json.loads(match)
                except json.JSONDecodeError:
                    continue

        # Try finding JSON array
        array_match = re.search(r'\[.*\]', text, re.DOTALL)
        if array_match:
            try:
                return json.loads(array_match.group())
            except json.JSONDecodeError as exc:
                last_error = exc

        logger.warning(
            "failed_to_extract_json",
            reason=str(last_error),
            text_preview=text[:200],
        )
        return None

    @classmethod
    def _load_json_payload(cls, content: str, *, strict: bool = False) -> dict[str, Any] | None:
        """Load a dict payload for finding-like JSON responses."""
        data = cls._extract_json(content)
        if data is None:
            if strict:
                raise StructuredOutputError(
                    "Model response did not contain valid JSON for finding output"
                )
            return None

        if isinstance(data, list):
            data = data[0] if data else {}

        if not isinstance(data, dict):
            if strict:
                raise StructuredOutputError(
                    "Model response did not contain an object for finding output"
                )
            return {}
        return data

    @staticmethod
    def _extract_kg_payload(data: dict[str, Any]) -> tuple[list[dict], list[dict]]:
        kg_block = data.get("kg_contribution")
        if isinstance(kg_block, dict):
            entities = kg_block.get("entities", kg_block.get("kg_entities", []))
            relationships = kg_block.get(
                "relationships",
                kg_block.get("kg_relationships", []),
            )
        else:
            entities = data.get("kg_entities", [])
            relationships = data.get("kg_relationships", [])

        if not isinstance(entities, list):
            entities = []
        if not isinstance(relationships, list):
            relationships = []
        return entities, relationships

    @staticmethod
    def _build_finding_data(
        data: dict[str, Any],
        *,
        fallback_content: str,
    ) -> FindingData:
        kg_entities, kg_relationships = ResponseParser._extract_kg_payload(data)
        citations = data.get("citations", [])
        if not isinstance(citations, list):
            citations = []
        return FindingData(
            title=data.get("title", "Untitled Finding"),
            content=data.get("content", fallback_content),
            confidence=float(data.get("confidence", 0.5)),
            kg_entities=kg_entities,
            kg_relationships=kg_relationships,
            citations=citations,
        )

    @classmethod
    def _validate_citation_contract(cls, citations: Any) -> None:
        if not isinstance(citations, list):
            raise FindingContractError("Research finding must include a citations array")

        for index, citation in enumerate(citations, start=1):
            if not isinstance(citation, dict):
                raise FindingContractError(
                    f"Citation #{index} must be an object"
                )
            missing = sorted(cls.REQUIRED_CITATION_KEYS.difference(citation.keys()))
            if missing:
                raise FindingContractError(
                    f"Citation #{index} is missing required keys: {', '.join(missing)}"
                )
            title = str(citation.get("title", "")).strip()
            source_type = str(citation.get("source_type", "")).strip()
            source_name = str(citation.get("source_name", "")).strip()
            supporting_snippet = str(citation.get("supporting_snippet", "")).strip()
            url = str(citation.get("url", "")).strip()
            doi = str(citation.get("doi", "")).strip()
            authors = citation.get("authors")
            if not title:
                raise FindingContractError(f"Citation #{index} must include a non-empty title")
            if not source_type:
                raise FindingContractError(f"Citation #{index} must include a non-empty source_type")
            if not source_name:
                raise FindingContractError(f"Citation #{index} must include a non-empty source_name")
            if not supporting_snippet:
                raise FindingContractError(
                    f"Citation #{index} must include a non-empty supporting_snippet"
                )
            if source_type != "finding" and not (url or doi):
                raise FindingContractError(
                    f"Citation #{index} must include at least one of url or doi"
                )
            if not isinstance(authors, list):
                raise FindingContractError(
                    f"Citation #{index} must include authors as an array"
                )

    @classmethod
    def _validate_kg_contribution_contract(
        cls,
        kg_block: Any,
    ) -> tuple[list[dict], list[dict]]:
        if not isinstance(kg_block, dict):
            raise FindingContractError(
                "Research finding must include a kg_contribution object"
            )

        entities = kg_block.get("entities")
        relationships = kg_block.get("relationships")
        if not isinstance(entities, list) or not entities:
            raise FindingContractError(
                "kg_contribution.entities must be a non-empty array"
            )
        if not isinstance(relationships, list):
            raise FindingContractError(
                "kg_contribution.relationships must be an array"
            )

        labels: set[str] = set()
        for index, entity in enumerate(entities, start=1):
            if not isinstance(entity, dict):
                raise FindingContractError(f"Entity #{index} must be an object")
            label = str(entity.get("label", "")).strip()
            node_type = str(entity.get("type", "")).strip()
            if not label:
                raise FindingContractError(f"Entity #{index} must include a non-empty label")
            if not node_type:
                raise FindingContractError(f"Entity #{index} must include a non-empty type")
            labels.add(label)

        if len(labels) > 1 and not relationships:
            raise FindingContractError(
                "kg_contribution.relationships must include at least one relationship when multiple entities are emitted"
            )

        for index, relationship in enumerate(relationships, start=1):
            if not isinstance(relationship, dict):
                raise FindingContractError(
                    f"Relationship #{index} must be an object"
                )
            source = str(relationship.get("source", "")).strip()
            target = str(relationship.get("target", "")).strip()
            rel_type = str(relationship.get("type", "")).strip()
            weight = relationship.get("weight")
            if not source or not target:
                raise FindingContractError(
                    f"Relationship #{index} must include non-empty source and target labels"
                )
            if source not in labels or target not in labels:
                raise FindingContractError(
                    f"Relationship #{index} must reference labels declared in kg_contribution.entities"
                )
            if not cls.RELATIONSHIP_TYPE_PATTERN.fullmatch(rel_type):
                raise FindingContractError(
                    f"Relationship #{index} has invalid type '{rel_type}'. Use concise snake_case labels."
                )
            try:
                numeric_weight = float(weight)
            except (TypeError, ValueError):
                raise FindingContractError(
                    f"Relationship #{index} must include a numeric weight"
                ) from None
            if numeric_weight < 0.0 or numeric_weight > 1.0:
                raise FindingContractError(
                    f"Relationship #{index} must have a weight between 0.0 and 1.0"
                )

        return entities, relationships

    @classmethod
    def parse_finding(cls, content: str, *, strict: bool = False) -> FindingData:
        """Parse a single finding from agent output."""
        data = cls._load_json_payload(content, strict=strict)
        if data is None:
            # Fallback: treat entire content as finding text
            return FindingData(
                title="Untitled Finding",
                content=content,
                confidence=0.5,
            )

        finding = cls._build_finding_data(data, fallback_content=content)
        if strict and (
            not finding.title.strip()
            or not finding.content.strip()
        ):
            raise StructuredOutputError(
                "Model returned incomplete JSON for finding output"
            )
        return finding

    @classmethod
    def parse_research_finding(
        cls,
        content: str,
        *,
        strict: bool = True,
    ) -> FindingData:
        """Parse and validate a research finding against the hard evidence contract."""
        data = cls._load_json_payload(content, strict=strict)
        if data is None:
            raise FindingContractError(
                "Research finding must be valid JSON"
            )

        finding = cls._build_finding_data(data, fallback_content=content)
        if not finding.title.strip() or not finding.content.strip():
            raise FindingContractError(
                "Research finding must include non-empty title and content"
            )
        if "citations" not in data:
            raise FindingContractError(
                "Research finding must include the citations key"
            )
        cls._validate_citation_contract(data.get("citations"))
        entities, relationships = cls._validate_kg_contribution_contract(
            data.get("kg_contribution")
        )
        finding.kg_entities = entities
        finding.kg_relationships = relationships
        return finding

    @classmethod
    def parse_findings(cls, content: str) -> list[FindingData]:
        """Parse potentially multiple findings from output."""
        data = cls._extract_json(content)
        if data is None:
            return [FindingData(title="Untitled Finding", content=content)]

        if isinstance(data, dict):
            # Check if it wraps a list of findings
            if "findings" in data:
                items = data["findings"]
            else:
                items = [data]
        elif isinstance(data, list):
            items = data
        else:
            return [FindingData(title="Untitled Finding", content=content)]

        findings = []
        for item in items:
            findings.append(FindingData(
                title=item.get("title", "Untitled Finding"),
                content=item.get("content", str(item)),
                confidence=float(item.get("confidence", 0.5)),
                kg_entities=item.get("kg_entities", []),
                kg_relationships=item.get("kg_relationships", []),
                citations=item.get("citations", []),
            ))
        return findings

    @classmethod
    def parse_review(cls, content: str, *, strict: bool = False) -> ReviewData:
        """Parse a peer review assessment."""
        data = cls._extract_json(content)
        if data is None:
            if strict:
                raise StructuredOutputError(
                    "Model response did not contain valid JSON for peer review output"
                )
            return ReviewData(
                methodology_critique="Unable to parse review",
                evidence_evaluation="Unable to parse review",
                novelty_assessment="Unable to parse review",
                confidence_rating=0.0,
                verdict="reject",
                revision_feedback="Review response was not parseable",
            )

        if isinstance(data, list):
            data = data[0] if data else {}

        review = ReviewData(
            methodology_critique=data.get("methodology_critique", ""),
            evidence_evaluation=data.get("evidence_evaluation", ""),
            novelty_assessment=data.get("novelty_assessment", ""),
            confidence_rating=float(data.get("confidence_rating", 0.0)),
            verdict=data.get("verdict", "reject"),
            revision_feedback=data.get("revision_feedback"),
        )
        if strict and (
            review.verdict not in {"approve", "reject", "revise"}
            or not review.methodology_critique.strip()
            or not review.evidence_evaluation.strip()
            or not review.novelty_assessment.strip()
        ):
            raise StructuredOutputError(
                "Model returned incomplete JSON for peer review output"
            )
        return review

    @classmethod
    def parse_decomposition(cls, content: str) -> DecompositionData:
        """Parse objective decomposition output."""
        data = cls._extract_json(content)
        if data is None:
            return DecompositionData()

        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("sub_objectives", [])
        else:
            return DecompositionData()

        sub_objectives = []
        for item in items:
            sub_objectives.append(SubObjectiveData(
                id=item.get("id", ""),
                title=item.get("title", ""),
                description=item.get("description", ""),
                role_class=item.get("role_class", "researcher"),
                dependency_type=item.get("dependency_type", "parallel"),
                depends_on=item.get("depends_on", []),
                impact_level=item.get("impact_level", "routine"),
                rationale=item.get("rationale", ""),
            ))
        return DecompositionData(sub_objectives=sub_objectives)

    @classmethod
    def parse_challenge(cls, content: str) -> ChallengeData:
        """Parse a Red Team challenge report."""
        data = cls._extract_json(content)
        if data is None:
            return ChallengeData(has_flaw=False)

        if isinstance(data, list):
            data = data[0] if data else {}

        return ChallengeData(
            has_flaw=bool(data.get("has_flaw", False)),
            flaw_type=data.get("flaw_type"),
            description=data.get("description"),
            counter_evidence=data.get("counter_evidence"),
            severity=data.get("severity"),
            confidence=float(data.get("confidence", 0.5)),
        )

    @classmethod
    def parse_kg_extraction(cls, content: str) -> KGExtractionData:
        """Parse KG entities and relationships from content."""
        data = cls._extract_json(content)
        if data is None:
            return KGExtractionData()

        if isinstance(data, list):
            data = data[0] if data else {}

        return KGExtractionData(
            entities=data.get("kg_entities", data.get("entities", [])),
            relationships=data.get("kg_relationships", data.get("relationships", [])),
        )

    @classmethod
    def parse_mutation(cls, content: str) -> MutationData:
        """Parse an evolution mutation proposal."""
        data = cls._extract_json(content)
        if data is None:
            return MutationData(
                mutated_prompt="",
                changes_description="Failed to parse mutation",
                expected_improvement="",
            )

        if isinstance(data, list):
            data = data[0] if data else {}

        return MutationData(
            mutated_prompt=data.get("mutated_prompt", ""),
            changes_description=data.get("changes_description", ""),
            expected_improvement=data.get("expected_improvement", ""),
        )

    @classmethod
    def parse_dream_cycle(cls, content: str) -> DreamCycleData:
        """Parse Dream Cycle consolidation output."""
        data = cls._extract_json(content)
        if data is None:
            return DreamCycleData()

        if isinstance(data, list):
            data = data[0] if data else {}

        return DreamCycleData(
            patterns_identified=data.get("patterns_identified", []),
            proposed_objectives=data.get("proposed_objectives", []),
            contradictions_found=data.get("contradictions_found", []),
        )

    @classmethod
    def parse_synthesis(cls, content: str) -> SynthesisData:
        """Parse synthesis output — may be plain markdown, not JSON."""
        return SynthesisData(content=content)

    @classmethod
    def parse_market_action(
        cls,
        content: str,
        *,
        strict: bool = False,
    ) -> MarketActionData:
        """Parse deterministic market action payloads used by the runtime."""
        data = cls._extract_json(content)
        if data is None:
            if strict:
                raise StructuredOutputError(
                    "Model response did not contain valid JSON for market action output"
                )
            return MarketActionData(action_type="unknown")

        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            if strict:
                raise StructuredOutputError(
                    "Model response did not contain an object for market action output"
                )
            return MarketActionData(action_type="unknown")

        action = MarketActionData(
            action_type=str(data.get("action_type", "")).strip(),
            persona_id=str(data.get("persona_id")).strip() if data.get("persona_id") is not None else None,
            template_code=str(data.get("template_code")).strip() if data.get("template_code") is not None else None,
            listing_id=str(data.get("listing_id")).strip() if data.get("listing_id") is not None else None,
            listing_kind=str(data.get("listing_kind")).strip() if data.get("listing_kind") is not None else None,
            instrument_symbol=str(data.get("instrument_symbol")).strip() if data.get("instrument_symbol") is not None else None,
            side=str(data.get("side")).strip() if data.get("side") is not None else None,
            price=float(data.get("price")) if data.get("price") is not None else None,
            quantity=float(data.get("quantity")) if data.get("quantity") is not None else None,
            details=data.get("details", {}) if isinstance(data.get("details", {}), dict) else {},
        )

        if strict:
            if not action.action_type:
                raise StructuredOutputError("Market action must include a non-empty action_type")
            if action.quantity is not None and action.quantity <= 0:
                raise StructuredOutputError("Market action quantity must be positive")
            if action.price is not None and action.price <= 0:
                raise StructuredOutputError("Market action price must be positive")
            if action.action_type in {"craft_listing", "purchase_listing"} and not action.listing_kind:
                raise StructuredOutputError("Market listing action must include listing_kind")
            if action.action_type == "place_order":
                if action.side not in {"buy", "sell"}:
                    raise StructuredOutputError("Market order action must include side buy|sell")
                if not action.instrument_symbol:
                    raise StructuredOutputError("Market order action must include instrument_symbol")
        return action
