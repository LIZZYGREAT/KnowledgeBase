"""Lifespan-owned coordinator; child processes own their SQLite connections."""

import asyncio
import logging
from pathlib import Path
import sys


class ManualResearchWorker:
    def __init__(self, root: Path, database: Path, has_work, interval: float = 30, on_failure=None):
        script_path = Path(root).resolve() / "tools" / "research.py"
        self.command = (
            sys.executable,
            str(script_path),
            "manual-tick", "--root", str(root), "--database", str(database),
        )
        self.has_work = has_work
        self.interval = interval
        self.on_failure = on_failure
        self.wakeup = asyncio.Event()
        self.wakeup.set()  # Recover persisted work at startup.
        self.task = None
        self.process = None

    def start(self):
        self.task = asyncio.create_task(self._run())

    def notify(self):
        self.wakeup.set()

    async def _run(self):
        while True:
            try:
                await asyncio.wait_for(self.wakeup.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass
            self.wakeup.clear()
            work = None
            try:
                work = self.has_work()
                if not work:
                    continue
                script_path = Path(self.command[1])
                if not script_path.is_file():
                    message = f"后台检索脚本不存在（{script_path}），请检查后端仓库目录配置。"
                    logging.getLogger(__name__).error(message)
                    self._record_failure(work, message)
                    continue
                launching = asyncio.create_task(asyncio.create_subprocess_exec(*self.command))
                try:
                    self.process = await asyncio.shield(launching)
                except asyncio.CancelledError as cancelled:
                    try:
                        self.process = await launching
                    except Exception:
                        logging.getLogger(__name__).exception("Executor startup failed during shutdown")
                    raise cancelled
                code = await self.process.wait()
                self.process = None
                if code:
                    logging.getLogger(__name__).warning("Manual Research executor exited with %s", code)
                    self._record_failure(work, "后台检索执行器启动检查失败，请查看后端日志，修复配置后重新提交检索。")
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception("Manual Research executor could not start")
                self._record_failure(work, "后台检索执行器无法启动，请查看后端日志后重试。")
            # Periodic retries cover lock contention and stale claims; avoid a busy loop.

    def _record_failure(self, work, message):
        if self.on_failure is not None and work:
            try:
                self.on_failure(work, message)
            except Exception:
                logging.getLogger(__name__).exception("Could not persist executor failure; coordinator will retry")

    async def stop(self):
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        self.process = None
