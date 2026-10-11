import hashlib
import json
from pathlib import Path
from urllib.error import URLError

import pytest
from pydantic import ValidationError

from backend.app.db.connection import connect_database
from backend.app.api.schemas import TermRewriteRequest
from backend.app.repositories.draft_repository import DraftRepository
from backend.app.repositories.proposal_repository import ProposalRepository
from backend.app.services.ai_client import (
    AIConfigurationError,
    AIProviderError,
    AIResponseError,
    DeepSeekClient,
    DeepSeekConfig,
    MockDeepSeekClient,
)
from backend.app.services.ai_gateway import (
    AIGateway,
    TERM_DEPTH_GUIDANCE,
    TASKS,
)
from backend.app.services.ai_proposal_service import AIProposalService
from backend.app.services.draft_service import DraftService
from backend.app.services.markdown_parser import parse_markdown
from backend.app.services.proposal_service import ProposalService


def test_mock_gateway_persists_validated_output_as_draft_bound_proposal():
    connection = connect_database(":memory:")
    content = "---\nschema_version: 1\nid: example\n---\n# Example\n"
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create(
        "document", "example", content, "a" * 40,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    client = MockDeepSeekClient(
        {"review_format_semantics": {"summary": "Looks clear", "findings": []}}
    )
    proposals = ProposalService(ProposalRepository(connection))
    ai = AIProposalService(
        Path(__file__).resolve().parents[2], drafts, proposals, AIGateway(client)
    )

    proposal = ai.generate("review_format_semantics", draft.id)

    assert proposal.kind == "format"
    assert proposal.target_id == "example"
    assert proposal.base_content_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert proposal.payload == {
        "task": "review_format_semantics",
        "draft_id": draft.id,
        "result": {"summary": "Looks clear", "findings": []},
    }
    assert proposal.provider == "mock"
    assert client.calls == ["review_format_semantics"]
    connection.close()


def test_term_generation_reuses_matching_proposal_and_rejecting_it_allows_fresh_generation():
    connection = connect_database(":memory:")
    content = (
        "---\nschema_version: 1\nid: replay\ntitle: Replay\ntype: concept\n"
        "depth: stub\naliases: []\ndomains: []\ntopics: []\ntags: []\nsources: []\n---\n# Replay\n"
    )
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("term", "replay", content, "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    client = MockDeepSeekClient({"draft_term": {"id": "replay", "title": "Replay", "type": "concept", "depth": "stub", "definition_zh": "Experience Replay 保留样本。", "definition_en": "Experience Replay retains examples."}})
    service = AIProposalService(Path(__file__).resolve().parents[2], drafts, proposals, AIGateway(client))
    first = service.generate("draft_term", draft.id)
    second = service.generate("draft_term", draft.id)
    assert first.id == second.id
    assert client.calls == ["draft_term"]
    proposals.reject(first.id, "Discard this explanation")
    fresh = service.generate("draft_term", draft.id)
    assert fresh.id != first.id
    assert client.calls == ["draft_term", "draft_term"]
    from backend.app.api.schemas import DraftView
    from dataclasses import asdict
    assert DraftView.model_validate(asdict(draft)).model_dump()["working_content_hash"] == first.base_content_hash
    connection.close()


def test_invalid_json_or_schema_does_not_create_proposal():
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    content = "draft"
    draft = drafts.create(
        "document", "example", content, "a" * 40,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    proposals = ProposalService(ProposalRepository(connection))
    invalid = MockDeepSeekClient(
        {"review_format_semantics": '{"summary": "missing findings"}'}
    )
    ai = AIProposalService(
        Path(__file__).resolve().parents[2], drafts, proposals, AIGateway(invalid)
    )

    with pytest.raises(AIResponseError, match="JSON schema"):
        ai.generate("review_format_semantics", draft.id)

    assert connection.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0
    connection.close()


def test_ai_task_registry_declares_output_contracts():
    assert set(TASKS) == {
        "suggest_metadata",
        "detect_terms",
        "review_format_semantics",
        "review_document",
        "draft_term",
        "rewrite_term_bilingual",
        "rewrite_research_card",
        "suggest_revision",
        "suggest_evidence",
        "research_candidate_analysis",
        "discover_terms",
    }
    assert all(task.output_model.model_json_schema() for task in TASKS.values())
    assert all(
        task.proposal_kind
        for task in TASKS.values()
        if task.output_usage == "proposal"
    )
    assert TASKS["research_candidate_analysis"].output_usage == "analysis"
    assert TASKS["research_candidate_analysis"].proposal_kind is None
    assert TASKS["discover_terms"].output_usage == "analysis"
    assert TASKS["discover_terms"].proposal_kind is None


def test_term_discovery_output_requires_explainable_readiness_fields():
    client = MockDeepSeekClient(
        {
            "discover_terms": {
                "candidates": [
                    {
                        "mention": "elastic weight consolidation",
                        "term_type": "concept",
                        "existing_term_id": None,
                        "confidence": 0.93,
                        "rationale": "A reusable continual learning method.",
                        "context_excerpt": "Elastic weight consolidation limits forgetting.",
                        "readiness": "high",
                        "recommendation_level": "core_gap",
                        "known_prerequisites": ["Fisher information"],
                        "missing_prerequisites": [],
                        "why_now": "It connects the selected focus to parameter importance.",
                    }
                ]
            }
        }
    )

    output = AIGateway(client).run(
        "discover_terms", {"lane": "concept", "focus": ["continual learning"]}
    )

    assert output.candidates[0].recommendation_level == "core_gap"
    assert output.candidates[0].why_now.startswith("It connects")


def test_research_analysis_prompt_limits_collection_suggestions_to_profile_context():
    client = MockDeepSeekClient(
        {
            "research_candidate_analysis": {
                "relevant": False,
                "profile_relevance": 0.2,
                "knowledge_relevance": 0.1,
                "novelty_to_library": 0.5,
                "matched_lenses": [],
                "matched_topics": [],
                "summary": "A paper summary.",
                "why_relevant": "It is not relevant.",
                "reading_reason": "No action is needed.",
                "summary_zh": "论文摘要。",
                "why_relevant_zh": "这篇论文与主题无关。",
                "reading_reason_zh": "无需采取行动。",
                "readiness": "medium",
                "known_prerequisites": [],
                "missing_prerequisites": ["Fisher information"],
                "why_now": "It can explain an open question in the selected focus.",
                "term_candidates": [],
                "existing_relations": [],
                "suggested_collection": None,
                "suggested_section": None,
            }
        }
    )

    AIGateway(client).run(
        "research_candidate_analysis", {"profile": {"allowed_collection_ids": []}}
    )

    prompt = client.messages[0][0]["content"]
    assert (
        "suggested_collection may only be one of profile.allowed_collection_ids"
        in prompt
    )
    assert "if that list is empty, suggested_collection must be null" in prompt
    assert (
        "If suggested_collection is null, suggested_section must also be null"
        in prompt
    )
    assert "Never invent a Collection id" in prompt
    assert (
        "existing_relations may reference only the exact (entity_type, entity_id) pairs"
        in prompt
    )
    assert "present in knowledge_context.cards" in prompt
    assert "Never invent, normalize, rename, or infer an entity id" in prompt
    assert "return an empty existing_relations list" in prompt
    assert "summary_zh" in prompt
    assert "reason_zh" in prompt


def test_term_generation_prompt_scales_to_depth_and_preserves_candidate_context():
    content = "---\nschema_version: 1\nid: feature-vector\ntitle: Feature Vector\ntype: concept\ndepth: standard\n---\n# Feature Vector\n"
    response = {
        "id": "feature-vector",
        "title": "Feature Vector",
        "type": "concept",
        "depth": "standard",
        "definition_zh": "编码器将输入映射为 d 维向量；下游分类器可用该表示作出预测。",
        "definition_en": "An encoder maps an input to a d-dimensional representation that a downstream classifier can use for prediction.",
    }
    candidate = {
        "display_name": "Feature Vector",
        "suggested_type": "concept",
        "evidence": [{
            "origin_type": "document",
            "origin_id": "encoder-note",
            "origin_title": "Encoder Note",
            "context_excerpt": "The encoder produces a feature vector for each image.",
            "rationale": "The passage describes a reusable representation.",
        }],
    }
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("term", "feature-vector", content, "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    client = MockDeepSeekClient({"draft_term": response})
    service = AIProposalService(
        Path(__file__).resolve().parents[2], drafts, proposals, AIGateway(client)
    )

    proposal = service.generate("draft_term", draft.id, {"term_candidate": candidate})

    prompt = client.messages[0][0]["content"]
    context = json.loads(client.messages[0][1]["content"])
    assert TERM_DEPTH_GUIDANCE in prompt
    assert "stub is the shortest complete explanation" in prompt
    assert "standard includes that same complete coverage" in prompt
    assert "deep includes that coverage and selectively explains" in prompt
    assert "concept examples show a task, operation, or input-to-output flow" in prompt
    assert "vocabulary examples use a natural technical or research sentence" in prompt
    assert "entity examples identify the concrete object" in prompt
    assert "Do not force equations on ordinary Terms" in prompt
    assert "Generate both definition_zh and definition_en" in prompt
    assert "invent results, citations, quotes, or Source IDs" in prompt
    assert context["draft"]["content"] == content
    assert context["request"]["term_candidate"] == candidate
    assert "terms" in context["registries"]
    assert "taxonomy" in context["registries"]
    assert proposal.payload["result"]["depth"] == "standard"
    assert len(client.calls) == 1
    connection.close()


def test_term_generation_and_bilingual_rewrite_share_depth_guidance():
    assert TERM_DEPTH_GUIDANCE in TASKS["draft_term"].instruction
    assert TERM_DEPTH_GUIDANCE in TASKS["rewrite_term_bilingual"].instruction
    assert "definition_zh and definition_en" in TASKS["draft_term"].instruction
    assert "Rewrite both complete Term explanations in one response" in TASKS["rewrite_term_bilingual"].instruction
    assert "definition_zh, definition_en, and rationale only" in TASKS["rewrite_term_bilingual"].instruction
    assert "same important facts, mechanisms, and concrete example" in TASKS["rewrite_term_bilingual"].instruction
    assert "never introduce an H1 or H2 heading" in TASKS["rewrite_term_bilingual"].instruction


def test_term_rewrite_request_allows_empty_requirements_and_rejects_language_selector():
    request = TermRewriteRequest.model_validate({
        "draft_id": "term-draft",
        "confirm_deepseek_transfer": True,
    })
    assert request.requirements == ""

    with pytest.raises(ValidationError):
        TermRewriteRequest.model_validate({
            "draft_id": "term-draft",
            "confirm_deepseek_transfer": True,
            "language": "en",
        })


@pytest.mark.parametrize("depth", ["stub", "standard", "deep"])
def test_term_draft_preserves_any_selected_depth_and_requires_bilingual_content(depth):
    content = (
        "---\nschema_version: 1\nid: selected-depth\ntitle: Selected Depth\n"
        "type: vocabulary\ndepth: {}\naliases: [selected alias]\nsources: [source-one]\n---\n"
        "# Selected Depth\n\nUser-written note.\n"
    ).format(depth)
    response = {
        "id": "selected-depth",
        "title": "Selected Depth",
        "type": "vocabulary",
        "depth": depth,
        "definition_zh": "在研究句子中出现的术语；例如：The result is state of the art，即表示当前结果具有先进水平。",
        "definition_en": "In a research sentence, state of the art means the best current result; for example, a paper may compare its score with the state of the art.",
    }
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("term", "selected-depth", content, "a" * 40, "b" * 64)
    service = AIProposalService(
        Path(__file__).resolve().parents[2],
        drafts,
        ProposalService(ProposalRepository(connection)),
        AIGateway(MockDeepSeekClient({"draft_term": response})),
    )

    proposal = service.generate("draft_term", draft.id)

    assert proposal.payload["result"]["depth"] == depth
    assert "depth: {}".format(depth) in proposal.payload["content"]
    assert "definition_zh" in proposal.payload["result"]
    assert "definition_en" in proposal.payload["result"]
    assert "User-written note." in proposal.payload["content"]
    assert drafts.get(draft.id).content == content
    connection.close()


def test_term_draft_rejects_identity_type_or_depth_different_from_the_current_draft():
    content = (
        "---\nschema_version: 1\nid: feature-vector\ntitle: Feature Vector\n"
        "type: concept\ndepth: stub\naliases: [FV]\ndomains: []\ntopics: []\n"
        "tags: []\nsources: []\n---\n# Feature Vector\n"
    )
    for field, value in (("id", "other-term"), ("type", "entity"), ("depth", "standard")):
        connection = connect_database(":memory:")
        drafts = DraftService(DraftRepository(connection))
        draft = drafts.create("term", "feature-vector", content, "a" * 40, "b" * 64)
        response = {
            "id": "feature-vector",
            "title": "Feature Vector",
            "type": "concept",
            "depth": "stub",
            "definition_zh": "特征向量用于表示输入；例如编码器会为图像输出一个向量。",
            "definition_en": "A feature vector represents an input; for example, an encoder can output one vector for an image.",
        }
        response[field] = value
        proposals = ProposalService(ProposalRepository(connection))
        service = AIProposalService(
            Path(__file__).resolve().parents[2],
            drafts,
            proposals,
            AIGateway(MockDeepSeekClient({"draft_term": response})),
        )

        with pytest.raises(AIResponseError, match="current Draft {}".format(field)):
            service.generate("draft_term", draft.id)

        assert connection.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0
        assert drafts.get(draft.id).content == content
        connection.close()


def test_bilingual_term_proposal_keeps_draft_metadata_through_adoption():
    content = (
        "---\n"
        "schema_version: 1\n"
        "id: ai-metadata-test-term\n"
        "title: Human Draft Title\n"
        "type: concept\n"
        "depth: standard\n"
        "aliases: [Existing Alias]\n"
        "domains: [artificial-intelligence]\n"
        "topics: [representation-learning]\n"
        "tags: [reviewed-tag]\n"
        "sources: [known-source]\n"
        "review:\n  human:\n    status: unreviewed\n"
        "provenance:\n  origin: human-authored\n  ai_assisted: false\n"
        "---\n"
        "User note that must remain.\n"
    )
    response = {
        "id": "ai-metadata-test-term",
        "title": "AI title suggestion",
        "type": "concept",
        "depth": "standard",
        "aliases": ["AI alias suggestion"],
        "definition_zh": "一种表示输入的向量；例如编码器可以为图像输出一个特征向量。",
        "definition_en": "A vector representation of an input; for example, an encoder can output a feature vector for an image.",
    }
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("term", "ai-metadata-test-term", content, "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    service = AIProposalService(
        Path(__file__).resolve().parents[2],
        drafts,
        proposals,
        AIGateway(MockDeepSeekClient({"draft_term": response})),
    )

    proposal = service.generate("draft_term", draft.id)
    proposed_content = proposal.payload["content"]
    proposed = parse_markdown(proposed_content)
    original = parse_markdown(content)

    assert proposed.frontmatter == original.frontmatter
    assert proposed.frontmatter_raw == original.frontmatter_raw
    assert proposal.payload["result"]["title"] == "Human Draft Title"
    assert proposal.payload["result"]["aliases"] == ["Existing Alias"]
    assert "# Human Draft Title" in proposed_content
    assert "AI title suggestion" not in proposed_content
    assert "AI alias suggestion" not in proposed_content
    assert "User note that must remain." in proposed_content
    assert drafts.get(draft.id).content == content

    proposals.apply_to_draft(proposal.id, draft, draft.revision)
    adopted = drafts.get(draft.id)
    assert parse_markdown(adopted.content).frontmatter == original.frontmatter
    assert "User note that must remain." in adopted.content
    assert "A vector representation of an input" in adopted.content
    assert "an encoder can output a feature vector" in adopted.content
    connection.close()


def test_bilingual_rewrite_replaces_both_sections_and_preserves_nonlanguage_content():
    content = (
        "---\nschema_version: 1\nid: feature-vector\ntitle: Feature Vector\n"
        "type: concept\ndepth: standard\naliases: [embedding]\nsources: [encoder-paper]\n---\n"
        "# Feature Vector\n\nUser-written context stays outside both language sections.\n\n"
        "## Editorial Note\n\nPreserve this independent Markdown section.\n\n"
        "## 一、中文解释\n\n编码器将输入转换为数值表示。\n\n"
        "## 二、English Explanation\n\nAn encoder maps input to numeric values.\n"
    )
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("term", "feature-vector", content, "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    client = MockDeepSeekClient({
        "rewrite_term_bilingual": {
            "definition_zh": "### 含义与机制\n\n编码器将输入映射为有限维特征向量，例如可供分类器读取。",
            "definition_en": "### Meaning and mechanism\n\nAn encoder maps an input to a finite-dimensional feature vector that a classifier can consume.",
            "rationale": "Aligns the definition, mechanism, and downstream example in both languages.",
        }
    })
    service = AIProposalService(
        Path(__file__).resolve().parents[2], drafts, proposals, AIGateway(client)
    )

    proposal = service.generate("rewrite_term_bilingual", draft.id, {
        "requirements": "Explain the vector dimension and how a classifier uses it.",
    })

    prompt = client.messages[0][0]["content"]
    context = json.loads(client.messages[0][1]["content"])
    proposed = proposal.payload["content"]
    original_frontmatter = content.split("---\n", 2)[1]
    proposed_frontmatter = proposed.split("---\n", 2)[1]
    assert TERM_DEPTH_GUIDANCE in prompt
    assert "rewrite both complete term explanations" in prompt.lower()
    assert "both languages must cover the same important facts" in prompt.lower()
    assert "Do not invent citations, quotes, sources, or Source IDs" in prompt
    assert context["request"] == {
        "requirements": "Explain the vector dimension and how a classifier uses it.",
    }
    assert proposed_frontmatter == original_frontmatter
    assert "User-written context stays outside both language sections." in proposed
    assert "## Editorial Note\n\nPreserve this independent Markdown section." in proposed
    assert "编码器将输入映射为有限维特征向量" in proposed
    assert "An encoder maps an input to a finite-dimensional feature vector" in proposed
    assert "编码器将输入转换为数值表示。" not in proposed
    assert proposal.payload["result"] == {
        "definition_zh": "### 含义与机制\n\n编码器将输入映射为有限维特征向量，例如可供分类器读取。",
        "definition_en": "### Meaning and mechanism\n\nAn encoder maps an input to a finite-dimensional feature vector that a classifier can consume.",
        "rationale": "Aligns the definition, mechanism, and downstream example in both languages.",
    }
    assert drafts.get(draft.id).content == content
    _, adopted = proposals.apply_to_draft(
        proposal.id, drafts.get(draft.id), draft.revision
    )
    assert "编码器将输入映射为有限维特征向量" in adopted.content
    assert "An encoder maps an input to a finite-dimensional feature vector" in adopted.content
    assert "## Editorial Note\n\nPreserve this independent Markdown section." in adopted.content
    assert parse_markdown(adopted.content).frontmatter == parse_markdown(content).frontmatter
    assert len(client.calls) == 1
    connection.close()


TERM_REWRITE_QUALITY_CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "term_rewrite_quality_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize(
    "quality_case",
    TERM_REWRITE_QUALITY_CASES,
    ids=[case["id"] for case in TERM_REWRITE_QUALITY_CASES],
)
def test_bilingual_rewrite_quality_examples_cover_all_term_types_and_depths(quality_case):
    term_id = quality_case["id"]
    content = (
        "---\n"
        f"schema_version: 1\nid: {term_id}\ntitle: {quality_case['title']}\n"
        f"type: {quality_case['term_type']}\ndepth: {quality_case['depth']}\n"
        "aliases: [quality sample]\nsources: [human-authored-example]\n---\n"
        f"# {quality_case['title']}\n\n"
        "## 一、中文解释\n\n现有中文正文。\n\n"
        "## 二、English Explanation\n\nExisting English body.\n"
    )
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("term", term_id, content, "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    client = MockDeepSeekClient({
        "rewrite_term_bilingual": {
            "definition_zh": quality_case["definition_zh"],
            "definition_en": quality_case["definition_en"],
            "rationale": "The paired example and the explanation use the same scenario.",
        }
    })
    service = AIProposalService(
        Path(__file__).resolve().parents[2], drafts, proposals, AIGateway(client)
    )

    proposal = service.generate("rewrite_term_bilingual", draft.id, {"requirements": ""})
    proposed = proposal.payload["content"]
    parsed = parse_markdown(proposed)

    assert parsed.frontmatter["type"] == quality_case["term_type"]
    assert parsed.frontmatter["depth"] == quality_case["depth"]
    assert parsed.frontmatter["aliases"] == ["quality sample"]
    assert parsed.frontmatter["sources"] == ["human-authored-example"]
    assert quality_case["example_zh"] in quality_case["definition_zh"]
    assert quality_case["example_en"] in quality_case["definition_en"]
    assert quality_case["definition_zh"] in proposed
    assert quality_case["definition_en"] in proposed
    assert "\n## " not in quality_case["definition_zh"]
    assert "\n## " not in quality_case["definition_en"]
    assert len(client.calls) == 1
    assert drafts.get(draft.id).content == content
    connection.close()


def test_bilingual_rewrite_rejects_section_boundary_output_before_storing_proposal():
    content = (
        "---\nschema_version: 1\nid: feature-vector\ntitle: Feature Vector\n"
        "type: concept\ndepth: standard\n---\n# Feature Vector\n\n"
        "## 一、中文解释\n\n旧中文解释。\n\n"
        "## 二、English Explanation\n\nOld English explanation.\n"
    )
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("term", "feature-vector", content, "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    client = MockDeepSeekClient({
        "rewrite_term_bilingual": {
            "definition_zh": "### 含义\n\n有效的中文解释。",
            "definition_en": "## Invalid top-level boundary\n\nThis would replace following content.",
            "rationale": "The English output changes the Markdown section boundary.",
        }
    })
    service = AIProposalService(
        Path(__file__).resolve().parents[2], drafts, proposals, AIGateway(client)
    )

    with pytest.raises(AIResponseError, match="preserve Markdown section boundaries"):
        service.generate("rewrite_term_bilingual", draft.id)

    assert connection.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0
    assert drafts.get(draft.id).content == content
    connection.close()


def test_research_analysis_cannot_be_persisted_as_a_proposal():
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    proposals = ProposalService(ProposalRepository(connection))
    client = MockDeepSeekClient()
    ai = AIProposalService(
        Path(__file__).resolve().parents[2], drafts, proposals, AIGateway(client)
    )

    with pytest.raises(ValueError, match="does not produce a Proposal"):
        ai.generate("research_candidate_analysis", "unused-draft")

    assert client.calls == []
    connection.close()


def test_term_draft_must_match_existing_term_draft_target():
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("document", "example", "draft", "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    ai = AIProposalService(
        Path(__file__).resolve().parents[2],
        drafts,
        proposals,
        AIGateway(
            MockDeepSeekClient(
                {
                    "draft_term": {
                        "id": "new-term",
                        "title": "New Term",
                        "type": "concept",
                        "depth": "stub",
                        "aliases": [],
                        "definition_zh": "一个术语。",
                        "definition_en": "A term.",
                    }
                }
            )
        ),
    )

    with pytest.raises(AIResponseError, match="must target a Term Draft"):
        ai.generate("draft_term", draft.id)

    assert connection.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0
    connection.close()


def test_metadata_suggestion_cannot_reference_unknown_registry_entries():
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("document", "example", "draft", "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    ai = AIProposalService(
        Path(__file__).resolve().parents[2],
        drafts,
        proposals,
        AIGateway(
            MockDeepSeekClient(
                {
                    "suggest_metadata": {
                        "changes": {"topics": ["unknown-topic"]},
                        "rationale": "Suggested topic.",
                    }
                }
            )
        ),
    )

    with pytest.raises(AIResponseError, match="unknown topic"):
        ai.generate("suggest_metadata", draft.id)

    assert connection.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0
    connection.close()


def test_revision_suggestion_with_invalid_canonical_content_is_not_saved():
    connection = connect_database(":memory:")
    drafts = DraftService(DraftRepository(connection))
    draft = drafts.create("document", "example", "draft", "a" * 40, "b" * 64)
    proposals = ProposalService(ProposalRepository(connection))
    ai = AIProposalService(
        Path(__file__).resolve().parents[2],
        drafts,
        proposals,
        AIGateway(
            MockDeepSeekClient(
                {
                    "suggest_revision": {
                        "proposed_content": "not a Markdown document",
                        "rationale": "Fix the document.",
                    }
                }
            )
        ),
    )

    with pytest.raises(AIResponseError, match="valid YAML frontmatter"):
        ai.generate("suggest_revision", draft.id)

    assert connection.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 0
    connection.close()


def test_deepseek_client_retries_transient_network_error_and_uses_json_mode():
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": '{"summary":"ok"}'}}]}
            ).encode("utf-8")

    def opener(request, timeout):
        requests.append((request, timeout))
        if len(requests) == 1:
            raise URLError("temporary")
        return Response()

    waits = []
    client = DeepSeekClient(
        DeepSeekConfig("server-secret", model="test-model", timeout_seconds=3, max_retries=1),
        opener=opener,
        sleeper=waits.append,
    )

    raw = client.complete(
        [{"role": "user", "content": "request"}], {"type": "object"}
    )

    assert json.loads(raw) == {"summary": "ok"}
    assert len(requests) == 2
    assert requests[1][1] == 3
    assert requests[1][0].get_header("Authorization") == "Bearer server-secret"
    assert json.loads(requests[1][0].data)["response_format"] == {"type": "json_object"}
    assert waits == [0.25]


def test_deepseek_client_stops_after_bounded_retries():
    attempts = []

    def opener(request, timeout):
        attempts.append(request)
        raise URLError("offline")

    client = DeepSeekClient(
        DeepSeekConfig("server-secret", model="test-model", max_retries=2),
        opener=opener,
        sleeper=lambda _: None,
    )
    with pytest.raises(AIProviderError, match="3 attempt") as error:
        client.complete([], {})
    assert len(attempts) == 3
    assert error.value.transient is True


def test_gateway_configuration_requires_server_side_key():
    client = DeepSeekClient(
        DeepSeekConfig("", model="test-model"), opener=lambda *_args, **_kwargs: None
    )
    with pytest.raises(AIConfigurationError, match="DEEPSEEK_API_KEY"):
        client.complete([], {})


def test_deepseek_configuration_requires_https():
    with pytest.raises(AIConfigurationError, match="HTTPS"):
        DeepSeekConfig("server-secret", model="test-model", base_url="http://example.test")


def test_empty_deepseek_model_environment_uses_yaml_default(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "ai.yaml.example").write_text(
        "model: yaml-model\napi_key_env: DEEPSEEK_API_KEY\n", encoding="utf-8"
    )

    monkeypatch.setenv("DEEPSEEK_MODEL", "")
    assert DeepSeekConfig.from_environment(tmp_path).model == "yaml-model"

    monkeypatch.setenv("DEEPSEEK_MODEL", "  ")
    assert DeepSeekConfig.from_environment(tmp_path).model == "yaml-model"

    monkeypatch.setenv("DEEPSEEK_MODEL", "environment-model")
    assert DeepSeekConfig.from_environment(tmp_path).model == "environment-model"


def test_empty_deepseek_model_without_yaml_default_is_a_configuration_error(
    tmp_path, monkeypatch
):
    (tmp_path / "config").mkdir()
    monkeypatch.setenv("DEEPSEEK_MODEL", "")
    with pytest.raises(AIConfigurationError, match="Configure a DeepSeek model"):
        DeepSeekConfig.from_environment(tmp_path)
