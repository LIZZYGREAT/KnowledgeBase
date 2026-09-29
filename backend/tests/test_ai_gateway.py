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


def test_all_phase_seven_tasks_have_output_schemas_and_proposal_kinds():
    assert set(TASKS) == {
        "suggest_metadata",
        "detect_terms",
        "review_format_semantics",
        "review_document",
        "draft_term",
        "suggest_revision",
        "suggest_evidence",
    }
    assert all(task.output_model.model_json_schema() for task in TASKS.values())
    assert all(task.proposal_kind for task in TASKS.values())


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
    with pytest.raises(AIProviderError, match="3 attempt"):
        client.complete([], {})
    assert len(attempts) == 3


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
