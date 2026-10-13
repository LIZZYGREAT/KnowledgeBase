from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_learning_context_daily_timer_is_independent_and_persistent():
    timer = (
        ROOT / "deploy" / "systemd" / "knowledgebase-learning-context.timer"
    ).read_text(encoding="utf-8")
    service = (
        ROOT / "deploy" / "systemd" / "knowledgebase-learning-context.service"
    ).read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 03:10:00" in timer
    assert "Persistent=true" in timer
    assert "Unit=knowledgebase-learning-context.service" in timer
    assert (
        "python /workspace/tools/learning_context.py sync --root /workspace"
        in service
    )
    assert "knowledgebase-research" not in timer + service
