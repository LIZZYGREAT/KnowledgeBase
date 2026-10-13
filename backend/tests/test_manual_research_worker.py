import asyncio
import sys

from backend.app.services.manual_research_worker import ManualResearchWorker
from backend.app.db.connection import connect_database
from backend.tests.test_research_runs import _service, _profile, FakeProvider
from backend.app.services.research_providers.base import ProviderPage


def test_web_coordinator_executes_persisted_manual_work_without_timer(tmp_path, monkeypatch):
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
