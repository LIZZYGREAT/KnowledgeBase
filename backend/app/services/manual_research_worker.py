"""Lifespan-owned coordinator; child processes own their SQLite connections."""

import asyncio
import logging
from pathlib import Path
import sys


class ManualResearchWorker:
    def __init__(self, root: Path, database: Path, has_work, interval: float = 30):
        self.command = (
            sys.executable,
            str(Path(__file__).resolve().parents[3] / "tools" / "research.py"),
            "manual-tick", "--root", str(root), "--database", str(database),
        )
        self.has_work = has_work
        self.interval = interval
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
            try:
                if not self.has_work():
                    continue
                self.process = await asyncio.create_subprocess_exec(*self.command)
                code = await self.process.wait()
                self.process = None
                if code:
                    logging.getLogger(__name__).warning("Manual Research executor exited with %s", code)
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.getLogger(__name__).exception("Manual Research executor could not start")
            # Periodic retries cover lock contention and stale claims; avoid a busy loop.

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
