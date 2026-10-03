from pathlib import Path
from types import SimpleNamespace

from backend.app.services.ai_client import DeepSeekConfig
from backend.app.services import research_wiring


def test_api_assembly_reuses_lifespan_services(tmp_path, monkeypatch):
    registry = object()
    dependencies = {
        "gateway": object(),
        "knowledge": object(),
        "collections": object(),
        "context_export": object(),
    }
    captured = {}

    monkeypatch.setattr(
        research_wiring.ResearchProfileRegistry,
        "load",
        lambda root: registry,
    )

    def capture(root, connection, **kwargs):
        captured.update(root=root, connection=connection, **kwargs)
        return "assembled-service"

    monkeypatch.setattr(research_wiring, "_assemble_research_service", capture)
    connection = object()

    result = research_wiring.assemble_research_service(
        tmp_path, connection, **dependencies
    )

    assert result == "assembled-service"
    assert captured["root"] == Path(tmp_path).resolve()
    assert captured["connection"] is connection
    assert captured["registry"] is registry
    for name, dependency in dependencies.items():
        assert captured[name] is dependency


def test_cli_builder_constructs_its_own_dependencies(tmp_path, monkeypatch):
    registry = SimpleNamespace(
        global_config=SimpleNamespace(
            analysis=SimpleNamespace(timeout_seconds=17),
        )
    )
    configured_ai = DeepSeekConfig(
        api_key="", model="test-model", timeout_seconds=29, max_retries=4
    )
    captured = {}
    client = object()
    gateway = object()
    knowledge = object()
    collections = object()
    context_export = object()

    monkeypatch.setattr(
        research_wiring.ResearchProfileRegistry,
        "load",
        lambda root: registry,
    )
    monkeypatch.setattr(
        DeepSeekConfig,
        "from_environment",
        classmethod(lambda cls, root: configured_ai),
    )
    monkeypatch.setattr(
        research_wiring, "DeepSeekClient", lambda config: _capture_client(captured, config, client)
    )
    monkeypatch.setattr(research_wiring, "AIGateway", lambda value: gateway)
    monkeypatch.setattr(
        research_wiring, "KnowledgeReadService", lambda root, connection: knowledge
    )
    monkeypatch.setattr(
        research_wiring, "CollectionService", lambda root, connection: collections
    )
    monkeypatch.setattr(
        research_wiring,
        "ContextExportService",
        lambda value, connection: context_export,
    )

    def capture_assembly(root, connection, **kwargs):
        captured.update(root=root, connection=connection, **kwargs)
        return "cli-service"

    monkeypatch.setattr(
        research_wiring, "_assemble_research_service", capture_assembly
    )
    connection = object()

    result = research_wiring.build_research_service_for_cli(tmp_path, connection)

    assert result == "cli-service"
    assert captured["root"] == Path(tmp_path).resolve()
    assert captured["connection"] is connection
    assert captured["registry"] is registry
    assert captured["gateway"] is gateway
    assert captured["knowledge"] is knowledge
    assert captured["collections"] is collections
    assert captured["context_export"] is context_export
    assert captured["client_config"].timeout_seconds == 17
    assert captured["client_config"].max_retries == 4


def _capture_client(captured, config, client):
    captured["client_config"] = config
    return client
