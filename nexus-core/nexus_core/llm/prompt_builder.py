from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from nexus_core.utils.file_context import AttachmentContext


class PromptBuilder:
    """Builds prompts by interpolating persona templates with context."""

    @staticmethod
    def build_agent_prompt(
        persona_template: str,
        objective_description: str,
        kg_context: str = "",
        institutional_memory: str = "",
    ) -> tuple[str, str]:
        """Build system and user prompts for an agent execution.

        Returns: (system_prompt, user_prompt)
        """
        system_prompt = persona_template.replace(
            "{objective}", objective_description
        ).replace(
            "{kg_context}", kg_context or "No prior knowledge available."
        ).replace(
            "{institutional_memory}", institutional_memory or "No institutional memory available."
        )

        user_prompt = f"""## Objective
{objective_description}

## Relevant Knowledge Graph Context
{kg_context or "No prior knowledge graph context available for this objective."}

## Institutional Memory (Lessons Learned)
{institutional_memory or "No relevant institutional memory for this objective."}

Please analyze this objective thoroughly and produce your findings in structured JSON format with the following schema:
{{
    "title": "Finding title",
    "content": "Detailed markdown content of your finding",
    "confidence": 0.0-1.0,
    "citations": [
        {{
            "title": "Source title",
            "source_type": "paper|patent|trial|web|report|dataset|finding",
            "source_name": "Journal, repository, or publisher",
            "url": "https://...",
            "doi": "10....",
            "published_date": "YYYY-MM-DD",
            "authors": ["Author A", "Author B"],
            "supporting_snippet": "The specific claim or evidence from the source that supports this finding"
        }}
    ],
    "kg_contribution": {{
        "entities": [
            {{"label": "entity name", "type": "concept|finding|hypothesis|entity|mechanism|policy|argument|evidence|metric|risk|outcome|intervention|population|biomarker|pathway", "properties": {{}}}}
        ],
        "relationships": [
            {{"source": "entity label", "target": "entity label", "type": "supports|contradicts|causes|correlates|enables|prevents|part_of|derives_from|outperforms|improves|inhibits|activates|treats|modulates|relates_to|trades_off_with", "weight": 0.0-1.0}}
        ]
    }}
}}

Return raw JSON only.
- Do not wrap the JSON in markdown fences.
- Do not add commentary before or after the JSON.
- Ensure the JSON is complete and valid.
- The `citations` key is mandatory even when empty.
- Every citation object must include every key shown above.
- For every external article, report, patent, trial, dataset, or web source you rely on, provide a non-empty `title`, `source_type`, `source_name`, `supporting_snippet`, and at least one of `url` or `doi`.
- If you do not rely on any external source, return an empty citations array.
- The `kg_contribution` key is mandatory.
- Extract the mechanistic concepts, entities, and relationships that are implicit in your prose. Do not leave KG-ready contributions trapped in narrative text.
- `kg_contribution.entities` must contain at least one entity.
- Every relationship must reference entity labels emitted in the same payload.
- Use concise snake_case relationship labels. If the exact relationship is not in the example list, emit the best specific snake_case predicate instead of dropping the edge.
- If you emit more than one entity, emit at least one relationship connecting the relevant entities.
- Do not use the legacy top-level `kg_entities` or `kg_relationships` keys."""

        return system_prompt, user_prompt

    @staticmethod
    def build_file_context_section(contexts: list[AttachmentContext]) -> str:
        """Build a prompt section from loaded file contexts.

        Only includes text-bearing attachments. Images are handled
        separately via the multimodal path.
        """
        text_parts: list[str] = []
        for ctx in contexts:
            if not ctx.text_content:
                continue
            size_kb = ctx.size_bytes / 1024
            text_parts.append(
                f"### File: {ctx.filename} ({size_kb:.0f} KB, {ctx.content_type})\n"
                f"{ctx.text_content}"
            )

        if not text_parts:
            return ""

        return "## Research Context Files\n\n" + "\n\n---\n\n".join(text_parts)

    @staticmethod
    def build_decomposition_prompt(
        objective_title: str,
        objective_description: str,
        kg_context: str = "",
        max_depth: int = 6,
        max_fanout: int = 8,
        file_context: str = "",
    ) -> tuple[str, str]:
        """Build prompts for objective decomposition by the Originator.

        Returns: (system_prompt, user_prompt)
        """
        system_prompt = """You are the Originator — the meta-cognitive orchestrator of a research civilization. Your role is to decompose complex objectives into a directed acyclic graph (DAG) of sub-objectives.

Rules:
1. Each sub-objective must be independently executable by a single specialized agent
2. Dependencies between sub-objectives must be explicit
3. The DAG must be acyclic — no circular dependencies
4. Maximum depth: {max_depth} levels
5. Maximum fan-out: {max_fanout} sub-objectives per parent
6. Each sub-objective needs: title, description, required role_class, dependency_type (sequential/parallel/conditional), impact_level (routine/high-impact)
7. You NEVER perform domain research yourself — you only decompose and delegate
8. When research context files are provided, use their content to inform your decomposition and embed relevant facts from these files in each sub-objective's description field""".replace("{max_depth}", str(max_depth)).replace("{max_fanout}", str(max_fanout))

        file_section = ""
        if file_context:
            file_section = f"""

{file_context}

IMPORTANT: The researcher has provided the above context files. Use their content to inform your decomposition. Embed relevant data points, gene names, identifiers, and facts from these files into each sub-objective's description so that agents executing those sub-objectives have the necessary context without needing the original files.
"""

        user_prompt = f"""## Objective to Decompose
**Title:** {objective_title}
**Description:** {objective_description}

## Existing Knowledge Context
{kg_context or "No prior knowledge available — this is a fresh research direction."}
{file_section}
Decompose this objective into a DAG of sub-objectives. Return your decomposition as JSON:
{{
    "sub_objectives": [
        {{
            "id": "sub_1",
            "title": "Sub-objective title",
            "description": "What this sub-objective should investigate/produce",
            "role_class": "researcher|synthesizer|critic|scout|...",
            "dependency_type": "parallel|sequential|conditional",
            "depends_on": [],
            "impact_level": "routine|high-impact",
            "rationale": "Why this sub-objective is needed"
        }}
    ]
}}

Ensure the decomposition is:
- Comprehensive (covers all aspects of the parent objective)
- Non-redundant (each sub-objective addresses a distinct aspect)
- Properly ordered (dependencies reflect logical prerequisite relationships)
- Balanced (roughly equal complexity across parallel branches)

Return raw JSON only.
- Do not wrap the JSON in markdown fences.
- Do not add commentary before or after the JSON.
- Ensure the JSON is complete and valid."""

        return system_prompt, user_prompt

    @staticmethod
    def build_review_prompt(
        finding_title: str,
        finding_content: str,
        impact_level: str = "routine",
        citation_confidence_score: float = 0.5,
    ) -> tuple[str, str]:
        """Build prompts for peer review of a finding.

        Returns: (system_prompt, user_prompt)
        """
        system_prompt = """You are a peer reviewer in a research civilization. Your role is to critically evaluate findings for quality, accuracy, and contribution value.

You must produce a structured assessment. Be rigorous but fair — your goal is epistemic quality, not gatekeeping. Provide specific, actionable feedback."""

        citation_note = ""
        if citation_confidence_score < 0.5:
            citation_note = f"\n**Citation Verification Score:** {citation_confidence_score:.2f} (LOW — many citations could not be verified against external sources. Scrutinize references carefully.)"
        elif citation_confidence_score < 1.0:
            citation_note = f"\n**Citation Verification Score:** {citation_confidence_score:.2f} (0=unverified, 1=all sources confirmed)"

        user_prompt = f"""## Finding to Review
**Title:** {finding_title}
**Impact Level:** {impact_level}{citation_note}

**Content:**
{finding_content}

Produce your review as JSON:
{{
    "methodology_critique": "Assessment of the methodology used",
    "evidence_evaluation": "Assessment of evidence quality and sufficiency",
    "novelty_assessment": "Assessment of novelty and contribution",
    "confidence_rating": 0.0-1.0,
    "verdict": "approve|reject|revise",
    "revision_feedback": "Specific feedback if verdict is revise or reject (null if approve)"
}}

Return raw JSON only.
- Use "approve" when the finding is materially ready to integrate, even if you would still suggest minor improvements.
- Use "revise" for findings that are directionally strong but need targeted fixes before they are fully solid.
- Use "reject" only for findings that are fundamentally unsupported, unsafe, or materially broken.
- Do not wrap the JSON in markdown fences.
- Do not add commentary before or after the JSON.
- Ensure the JSON is complete and valid."""

        return system_prompt, user_prompt

    @staticmethod
    def build_challenge_prompt(
        finding_title: str,
        finding_content: str,
        kg_context: str = "",
    ) -> tuple[str, str]:
        """Build prompts for Red Team challenge of a validated finding.

        Returns: (system_prompt, user_prompt)
        """
        system_prompt = """You are a Red Team agent — an adversarial critic in a research civilization. Your mission is to find genuine flaws in validated findings. You earn bounties for legitimate challenges but are penalized for frivolous ones.

Focus on: logical inconsistencies, methodological weaknesses, unsupported claims, contradictions with known evidence, and hidden assumptions."""

        user_prompt = f"""## Validated Finding to Challenge
**Title:** {finding_title}

**Content:**
{finding_content}

## Known Knowledge Graph Context
{kg_context or "No additional context available."}

Attempt to challenge this finding. Return your challenge as JSON:
{{
    "has_flaw": true|false,
    "flaw_type": "methodological|logical|evidential|contradictory|null",
    "description": "Description of the flaw found (or null if no flaw)",
    "counter_evidence": "Counter-evidence or reasoning (or null)",
    "severity": "minor|major|critical|null",
    "confidence": 0.0-1.0
}}

If you cannot find a genuine flaw, set has_flaw to false. Do NOT fabricate challenges."""

        return system_prompt, user_prompt

    @staticmethod
    def build_synthesis_prompt(
        objective_title: str,
        findings: list[dict],
    ) -> tuple[str, str]:
        """Build prompts for synthesizing multiple findings into a coherent report.

        Returns: (system_prompt, user_prompt)
        """
        system_prompt = """You are a Systems Synthesizer in a research civilization. Your role is to combine findings from multiple specialized agents into a coherent, well-structured report that addresses the original objective.

Your synthesis should:
1. Identify common themes and patterns across findings
2. Highlight areas of agreement and disagreement
3. Present a balanced, multi-perspective analysis
4. Draw actionable conclusions where the evidence supports them
5. Acknowledge limitations and areas needing further investigation"""

        findings_text = ""
        for i, f in enumerate(findings, 1):
            findings_text += f"\n### Finding {i}: {f.get('title', 'Untitled')}\n{f.get('content', 'No content')}\n"

        user_prompt = f"""## Objective
{objective_title}

## Findings to Synthesize
{findings_text}

Produce a comprehensive synthesis as a structured markdown document that addresses the original objective by integrating all provided findings."""

        return system_prompt, user_prompt

    @staticmethod
    def build_dream_cycle_prompt(
        recent_kg_summary: str,
        kg_stats: dict,
    ) -> tuple[str, str]:
        """Build prompts for the Dream Cycle consolidation.

        Returns: (system_prompt, user_prompt)
        """
        system_prompt = """You are the Nightwatch Consolidator — a meta-cognitive agent that operates during low-activity periods. Your role is to review recent knowledge graph additions and identify cross-cutting patterns, unexplored connections, and potential research directions that individual agents may have missed.

Focus on:
1. Unconnected KG clusters that share semantic similarity
2. Contradictions between validated findings
3. High-confidence claims that lack supporting diversity (single evidence source)
4. Emergent patterns across multiple findings"""

        user_prompt = f"""## Recent Knowledge Graph Activity
{recent_kg_summary}

## KG Statistics
- Total nodes: {kg_stats.get('node_count', 0)}
- Total edges: {kg_stats.get('edge_count', 0)}
- Average confidence: {kg_stats.get('avg_confidence', 0):.3f}

Analyze the recent KG activity and propose exploratory research directions. Return as JSON:
{{
    "patterns_identified": [
        {{"description": "Pattern description", "supporting_nodes": ["node labels"], "confidence": 0.0-1.0}}
    ],
    "proposed_objectives": [
        {{"title": "Proposed objective", "description": "What to investigate", "rationale": "Why this is promising", "linked_nodes": ["node labels"]}}
    ],
    "contradictions_found": [
        {{"description": "Contradiction description", "nodes_involved": ["node labels"]}}
    ]
}}"""

        return system_prompt, user_prompt

    @staticmethod
    def build_mutation_prompt(
        current_prompt: str,
        performance_summary: str,
        mutation_type: str = "prompt_edit",
        donor_prompt_excerpt: str | None = None,
    ) -> tuple[str, str]:
        """Build prompts for evolutionary mutation of a persona's system prompt.

        Returns: (system_prompt, user_prompt)
        """
        system_prompt = """You are an evolutionary engineer. Your task is to propose a mutation to an agent's system prompt that could improve its performance. The mutation should be targeted and conservative — no more than 30% change from the original."""

        donor_section = (
            f"\n## Donor Prompt Fragment\n{donor_prompt_excerpt}\n"
            if donor_prompt_excerpt
            else ""
        )

        user_prompt = f"""## Current System Prompt
{current_prompt}

## Performance Summary
{performance_summary}
{donor_section}

## Mutation Type: {mutation_type}

Propose a mutated version of the system prompt that addresses the performance gaps. Return as JSON:
{{
    "mutated_prompt": "The full mutated system prompt",
    "changes_description": "What was changed and why",
    "expected_improvement": "What improvement is expected"
}}"""

        return system_prompt, user_prompt

    @staticmethod
    def build_market_action_prompt(
        *,
        persona_name: str,
        objective_title: str,
        action_type: str,
        action_context: str,
    ) -> tuple[str, str]:
        """Build a deterministic prompt/contract wrapper for market actions."""
        system_prompt = (
            "You are an autonomous market participant in the NEXUS civilization. "
            "Actions must be machine-valid, bounded, and directly attributable."
        )

        user_prompt = f"""## Market Objective
{objective_title}

## Acting Persona
{persona_name}

## Action
{action_type}

## Context
{action_context}

Return raw JSON only with:
{{
    "action_type": "craft_listing|purchase_listing|place_order|fulfill_service",
    "persona_id": "uuid-or-null",
    "template_code": "template code when relevant",
    "listing_id": "listing uuid when relevant",
    "listing_kind": "soft_good|hard_service when relevant",
    "instrument_symbol": "symbol when relevant",
    "side": "buy|sell when relevant",
    "price": positive number when relevant,
    "quantity": positive number when relevant,
    "details": {{}}
}}"""

        return system_prompt, user_prompt
