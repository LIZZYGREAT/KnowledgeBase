import json
import subprocess

from tools.learning_context import main
from backend.app.services.learning_context_service import LearningContextService


def test_cli_dry_run_reports_changes_without_writing_baselines(tmp_path, capsys):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "knowledge" / "documents" / "learning" / "gem-note.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "---\nschema_version: 1\nid: gem-note\ntitle: GEM Note\ntype: learning-note\n"
        "domains: []\ntopics: []\ntags: []\nsources: []\n---\n\n"
        "## Mechanism\n\nGEM projects the gradient.\n",
        encoding="utf-8",
    )
    LearningContextService(tmp_path).set_sources(["gem-note"])
    status_path = tmp_path / "storage" / "learning-context" / "state.json"
    status_before = status_path.read_text(encoding="utf-8")

    exit_code = main(["sync", "--root", str(tmp_path), "--dry-run"])

    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["state"] == "dry_run"
    assert result["source_results"][0]["action"] == "analyze"
    assert status_path.read_text(encoding="utf-8") == status_before
    assert not (tmp_path / "storage" / "learning-context" / "topics").exists()
