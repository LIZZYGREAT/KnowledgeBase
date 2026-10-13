import asyncio
import sys
from pathlib import Path

import backend.app.services.manual_research_worker as worker_module
from backend.app.services.manual_research_worker import ManualResearchWorker
from backend.app.db.connection import connect_database
from backend.tests.test_research_runs import _service, _profile, FakeProvider
from backend.app.services.research_providers.base import ProviderPage


def test_web_coordinator_executes_persisted_manual_work_without_timer(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_module, "__file__", "/app/backend/app/services/manual_research_worker.py")
    script = tmp_path / "tools" / "research.py"
    script.parent.mkdir()
    script.write_text("# test executor entry point\n", encoding="utf-8")
    database = tmp_path / "manual.db"
    connection = connect_database(database)
    service, _, _, _ = _service(tmp_path, connection, FakeProvider([]))
    queued = service.queue_manual_run("continual-learning")
    completed = asyncio.Event()
    commands = []

    class Process:
        returncode = 0

        async def wait(self):
            # The executor owns a new connection; no web connection is passed to it.
            child_connection = connect_database(database)
            child, _, _, _ = _service(tmp_path, child_connection, FakeProvider([ProviderPage(works=())]))
            run = child.manual_tick()
            assert run.request_id == queued.id
            child_connection.close()
            completed.set()
            return 0

    async def launch(*command):
        commands.append(command)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)

    async def exercise():
        worker = ManualResearchWorker(tmp_path, database, lambda: True, interval=30)
        worker.start()
        await asyncio.wait_for(completed.wait(), timeout=2)
        await worker.stop()

    asyncio.run(exercise())
    assert len(commands) == 1
    assert commands[0][0] == sys.executable
    assert Path(commands[0][1]) == script.resolve()
    assert commands[0][2] == "manual-tick"
    assert service.run_request_repository.get(queued.id).status == "completed"
    assert len(service.run_repository.list_for_profile("continual-learning")) == 1
    connection.close()


def test_manual_tick_never_runs_due_profiles_and_retries_busy_lock(tmp_path):
    connection = connect_database(":memory:")
    provider = FakeProvider([ProviderPage(works=())])
    service, _, _, ai = _service(tmp_path, connection, provider)
    assert service.manual_tick() is None
    assert provider.calls == 0
    queued = service.queue_manual_run("continual-learning")
    assert service.global_lock.try_acquire()
    assert service.manual_tick() is None
    assert service.run_request_repository.get(queued.id).status == "pending"
    service.global_lock.release()
    assert service.manual_tick().request_id == queued.id
    assert service.manual_tick() is None
    assert ai.calls == []
    connection.close()


def test_manual_tick_ai_disabled_does_not_call_ai(tmp_path):
    connection = connect_database(":memory:")
    profile = _profile()
    profile = profile.model_copy(update={"ai_analysis": profile.ai_analysis.model_copy(update={"enabled": False})})
    from backend.tests.test_research_runs import _provider_work
    service, _, _, ai = _service(tmp_path, connection, FakeProvider([ProviderPage(works=(_provider_work(),))]), profile=profile)
    service.queue_manual_run(profile.id)
    run = service.manual_tick()
    assert run.new_work_count == 1
    assert run.analyzed_count == run.surfaced_count == 0
    assert ai.calls == []
    assert connection.execute("SELECT COUNT(*) FROM research_search_state").fetchone()[0] == 0
    connection.close()


def test_worker_shutdown_terminates_executor(tmp_path, monkeypatch):
    script = tmp_path / "tools" / "research.py"
    script.parent.mkdir()
    script.write_text("# test executor entry point\n", encoding="utf-8")
    started = asyncio.Event()

    class Process:
        returncode = None
        stopped = False

        async def wait(self):
            started.set()
            if not self.stopped:
                await asyncio.Event().wait()
            self.returncode = -15
            return self.returncode

        def terminate(self):
            self.stopped = True

    process = Process()

    async def launch(*command):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)

    async def exercise():
        worker = ManualResearchWorker(tmp_path, tmp_path / "db", lambda: True)
        worker.start()
        await asyncio.wait_for(started.wait(), timeout=2)
        await worker.stop()
        assert process.stopped

    asyncio.run(exercise())


def test_executor_start_failure_is_queryable_and_never_reclaims_active_work(tmp_path, monkeypatch):
    script = tmp_path / "tools" / "research.py"
    script.parent.mkdir()
    script.write_text("# test executor entry point\n", encoding="utf-8")
    connection = connect_database(":memory:")
    provider = FakeProvider([])
    service, runs, _, ai = _service(tmp_path, connection, provider)
    queued = service.queue_manual_run("continual-learning")
    failed = asyncio.Event()

    async def launch(*command):
        raise OSError("cannot start child")

    def record_failure(record, message):
        service.fail_unstarted_request(record.id, message)
        failed.set()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)

    async def exercise():
        worker = ManualResearchWorker(tmp_path, tmp_path / "db", lambda: queued, on_failure=record_failure)
        worker.start()
        await asyncio.wait_for(failed.wait(), timeout=2)
        await worker.stop()

    asyncio.run(exercise())
    assert service.run_request_repository.get(queued.id).status == "failed"
    run = runs.list_for_profile(queued.profile_id)[0]
    assert run.request_id == queued.id and run.status == "failed"
    assert "无法启动" in run.error_summary
    assert provider.calls == 0 and ai.calls == []
    active = service.queue_manual_run("continual-learning")
    service.run_request_repository.claim_next(service.now())
    service.fail_unstarted_request(active.id, "must not overwrite running request")
    assert service.run_request_repository.get(active.id).status == "claimed"
    connection.close()


def test_missing_executor_script_fails_the_queued_request_with_a_clear_error(tmp_path):
    connection = connect_database(":memory:")
    service, runs, _, _ = _service(tmp_path, connection, FakeProvider([]))
    queued = service.queue_manual_run("continual-learning")
    failed = asyncio.Event()

    def record_failure(record, message):
        service.fail_unstarted_request(record.id, message)
        failed.set()

    async def exercise():
        worker = ManualResearchWorker(tmp_path, tmp_path / "db", lambda: queued, on_failure=record_failure)
        worker.start()
        await asyncio.wait_for(failed.wait(), timeout=2)
        await worker.stop()

    asyncio.run(exercise())

    assert service.run_request_repository.get(queued.id).status == "failed"
    run = runs.list_for_profile(queued.profile_id)[0]
    assert run.request_id == queued.id and run.status == "failed"
    assert "后台检索脚本不存在" in run.error_summary
    assert str(tmp_path / "tools" / "research.py") in run.error_summary
    connection.close()
