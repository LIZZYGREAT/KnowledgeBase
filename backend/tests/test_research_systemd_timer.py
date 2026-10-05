from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TIMER_PATH = REPOSITORY_ROOT / "deploy" / "systemd" / "knowledgebase-research.timer"


def test_research_timer_waits_after_the_previous_service_becomes_inactive():
    content = TIMER_PATH.read_text(encoding="utf-8")
    timer_section = content.split("[Timer]", 1)[1].split("[Install]", 1)[0]
    settings = {
        key: value
        for line in timer_section.splitlines()
        if "=" in line and not line.lstrip().startswith("#")
        for key, value in [line.split("=", 1)]
    }

    assert settings["OnBootSec"] == "2min"
    assert settings["OnUnitInactiveSec"] == "2min"
    assert "OnUnitActiveSec" not in settings
    assert "Persistent" not in settings
