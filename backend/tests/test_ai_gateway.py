import hashlib
import json
from pathlib import Path
from urllib.error import URLError

import pytest

from backend.app.db.connection import connect_database
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
    TASKS,
)
from backend.app.services.ai_proposal_service import AIProposalService
from backend.app.services.draft_service import DraftService
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
    content = "---\nschema_version: 1\nid: replay\n---\n"
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
        "rewrite_term_language",
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
                        "definition": "A definition.",
                    }
                }
            )
        ),
    )

    with pytest.raises(AIResponseError, match="target Term Draft id"):
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
