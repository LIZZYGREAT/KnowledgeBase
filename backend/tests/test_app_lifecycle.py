import asyncio
from pathlib import Path
import shutil
import subprocess

from backend.app.main import app


_ROOT = Path(__file__).resolve().parents[2]


def test_application_initializes_phase_services_from_configured_paths(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    shutil.copytree(_ROOT / "config", repository / "config")
    shutil.copytree(_ROOT / "knowledge", repository / "knowledge")
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
            assert app.state.ai_proposal_service.repository_root == repository.resolve()
            assert app.state.runtime_connection.execute("SELECT 1").fetchone()[0] == 1

    asyncio.run(inspect_application())
    assert database_path.is_file()
