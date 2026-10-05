import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKUP_SCRIPT = REPOSITORY_ROOT / "scripts" / "production-backup.sh"


@pytest.mark.parametrize("backup_exit_code", [0, 23])
def test_production_backup_restarts_services_after_snapshot(tmp_path, backup_exit_code):
    shell = os.environ.get("KB_POSIX_SHELL") or shutil.which("sh")
    if shell is None:
        pytest.skip("a POSIX shell is required to exercise the production backup script")

    call_log = tmp_path / "docker-calls.txt"
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$DOCKER_CALL_LOG\"\n"
        "if [ \"$*\" = \"compose --env-file .env -f docker-compose.production.yml run --rm --no-deps --entrypoint python backend /workspace/scripts/backup.py\" ]; then\n"
        "  exit \"${FAKE_DOCKER_BACKUP_EXIT:-0}\"\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = str(tmp_path) + os.pathsep + environment.get("PATH", "")
    environment["DOCKER_CALL_LOG"] = str(call_log)
    environment["FAKE_DOCKER_BACKUP_EXIT"] = str(backup_exit_code)

    result = subprocess.run(
        [shell, str(BACKUP_SCRIPT)],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == backup_exit_code
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "compose --env-file .env -f docker-compose.production.yml stop frontend backend",
        "compose --env-file .env -f docker-compose.production.yml run --rm --no-deps --entrypoint python backend /workspace/scripts/backup.py",
        "compose --env-file .env -f docker-compose.production.yml up -d backend frontend",
    ]
