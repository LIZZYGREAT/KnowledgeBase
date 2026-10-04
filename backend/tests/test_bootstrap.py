from pathlib import Path
from types import SimpleNamespace

from backend.app import bootstrap
from backend.app.db.connection import connect_database
from backend.app.services.ai_client import DeepSeekConfig


def test_research_configuration_uses_the_global_analysis_timeout(tmp_path, monkeypatch):
    registry = SimpleNamespace(
        global_config=SimpleNamespace(
            analysis=SimpleNamespace(timeout_seconds=17),
        )
    )
    configured_ai = DeepSeekConfig(
        api_key="key",
        model="test-model",
        base_url="https://example.test",
        timeout_seconds=29,
        max_retries=4,
    )
    monkeypatch.setattr(
        bootstrap.ResearchProfileRegistry,
        "load",
        lambda root: registry,
    )
    monkeypatch.setattr(
        DeepSeekConfig,
        "from_environment",
        classmethod(lambda cls, root: configured_ai),
    )

    loaded_registry, config = bootstrap.load_research_configuration(tmp_path)

    assert loaded_registry is registry
    assert config.api_key == "key"
    assert config.model == "test-model"
    assert config.base_url == "https://example.test"
    assert config.timeout_seconds == 17
    assert config.max_retries == 4


def test_research_components_share_gateway_and_runtime_dependencies(tmp_path, monkeypatch):
    (tmp_path / "knowledge" / "sources").mkdir(parents=True)
    registry = SimpleNamespace(
        global_config=SimpleNamespace(
            providers=SimpleNamespace(timeout_seconds=23, max_retries=5),
            analysis=SimpleNamespace(timeout_seconds=17, max_context_entities=6),
        )
    )
    config = DeepSeekConfig(
        api_key="",
        model="test-model",
        timeout_seconds=17,
        max_retries=2,
    )
    monkeypatch.setattr(
        bootstrap,
        "load_research_configuration",
        lambda root: (registry, config),
    )
    connection = connect_database(":memory:")

    components = bootstrap.build_research_components(tmp_path, connection)

    service = components.research_service
    assert components.repository_root == Path(tmp_path).resolve()
    assert components.deepseek_config is config
    assert service.analysis_service.gateway is components.ai_gateway
    assert service.context_builder.knowledge is components.knowledge_read_service
    assert service.context_builder.collections is components.collection_service
    assert service.context_builder.context_export is components.context_export_service
    assert components.context_export_service.knowledge is components.knowledge_read_service
    assert service.providers["arxiv"].client.timeout_seconds == 23
    assert service.providers["arxiv"].client.max_retries == 5
    connection.close()


def test_research_cli_uses_the_shared_component_builder(tmp_path, monkeypatch, capsys):
    from tools import research

    connection = SimpleNamespace(close=lambda: None)
    service = SimpleNamespace(tick=lambda: None)
    components = SimpleNamespace(research_service=service)
    captured = {}
    monkeypatch.setattr(research, "connect_database", lambda path: connection)
    monkeypatch.setattr(
        research,
        "build_research_components",
        lambda root, value: captured.update(root=root, connection=value) or components,
    )

    result = research._execute(
        tmp_path,
        tmp_path / "runtime.db",
        SimpleNamespace(command="tick"),
    )

    assert result == 0
    assert captured == {"root": Path(tmp_path), "connection": connection}
    assert "No queued manual request" in capsys.readouterr().out
