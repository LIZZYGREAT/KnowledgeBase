import asyncio
from pathlib import Path
import shutil
import subprocess

import yaml

from backend.app.main import app
from backend.app.services.ai_client import DeepSeekConfig


_ROOT = Path(__file__).resolve().parents[2]


def test_application_initializes_phase_services_from_configured_paths(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    shutil.copytree(_ROOT / "config", repository / "config")
    research_config_path = repository / "config" / "research" / "research.yaml"
    research_config = yaml.safe_load(
        research_config_path.read_text(encoding="utf-8")
    )
    research_config["analysis"]["timeout_seconds"] = 37
    research_config_path.write_text(
        yaml.safe_dump(research_config, sort_keys=False), encoding="utf-8"
    )
    profile_path = (
        repository / "config" / "research" / "profiles" / "continual-learning.yaml"
    )
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["context"]["documents"] = []
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    (repository / "knowledge").mkdir()
    shutil.copytree(
        _ROOT / "knowledge" / "taxonomy",
        repository / "knowledge" / "taxonomy",
    )
    for relative in (
        "documents/papers",
        "documents/learning",
        "documents/courses",
        "terms",
        "sources",
    ):
        (repository / "knowledge" / relative).mkdir(parents=True, exist_ok=True)
    database_path = tmp_path / "runtime" / "custom.db"
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    monkeypatch.setenv("KNOWLEDGE_REPO_PATH", str(repository))
    monkeypatch.setenv("DATABASE_PATH", str(database_path))

    async def inspect_application():
        async with app.router.lifespan_context(app):
            assert app.state.repository_root == repository.resolve()
            assert app.state.database_path == database_path
            assert app.state.git_manager.repository_root == repository.resolve()
            assert app.state.publisher.repository_root == repository.resolve()
            assert app.state.import_service.repository_root == repository.resolve()
            assert app.state.ai_gateway.provider == "deepseek"
            assert (
                app.state.ai_gateway.client.config.timeout_seconds
                == DeepSeekConfig.from_environment(repository).timeout_seconds
            )
            assert app.state.ai_proposal_service.repository_root == repository.resolve()
            assert app.state.ai_proposal_service.gateway is app.state.ai_gateway
            research_gateway = app.state.research_service.analysis_service.gateway
            assert research_gateway is not app.state.ai_gateway
            assert research_gateway.client.config.timeout_seconds == 37
            assert app.state.knowledge_read_service.repository_root == repository.resolve()
            assert app.state.context_export_service.knowledge is app.state.knowledge_read_service
            assert app.state.research_service.context_builder.knowledge is app.state.knowledge_read_service
            assert app.state.research_service.context_builder.collections is app.state.collection_service
            assert app.state.research_service.context_builder.context_export is app.state.context_export_service
            assert app.state.research_service.profile_registry.get("continual-learning") is not None
            assert app.state.usage_service.connection is app.state.runtime_connection
            assert app.state.ui_summary_service.connection is app.state.runtime_connection
            assert app.state.runtime_connection.execute("SELECT 1").fetchone()[0] == 1

    asyncio.run(inspect_application())
    assert database_path.is_file()
