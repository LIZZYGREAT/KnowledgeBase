"""Cross-platform non-blocking process lock for Research Runs."""

import os
from pathlib import Path
from threading import Lock, get_ident


class GlobalResearchLock:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._file = None
        self._state_lock = Lock()
        self._owner_thread_id = None

    @property
    def held(self) -> bool:
        with self._state_lock:
            return self._file is not None

    def try_acquire(self) -> bool:
        with self._state_lock:
            if self._file is not None:
                return False
            return self._acquire_locked()

    def _acquire_locked(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        self._file = handle
        self._owner_thread_id = get_ident()
        return True

    def release(self) -> None:
        with self._state_lock:
            handle = self._file
            if handle is None:
                return
            if self._owner_thread_id != get_ident():
                raise RuntimeError("Research lock must be released by its owner thread")
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
                self._file = None
                self._owner_thread_id = None
