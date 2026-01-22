from __future__ import annotations

import contextlib
import io
import os
import sys
from dataclasses import dataclass
from pathlib import Path


def _default_lock_path() -> Path:
    # Keep under ~/.gemini to align with the default browser profile location.
    base = Path.home() / ".gemini" / "browser-mcp"
    return base / "extension_gateway.lock"


def _rescue_lock_path() -> Path:
    base = Path.home() / ".gemini" / "browser-mcp"
    return base / "extension_gateway_rescue.lock"


@dataclass(slots=True)
class LeaderLock:
    """Best-effort inter-process leader lock.

    The goal is to ensure only one Browser MCP process binds the extension gateway ports.
    Others become peers and proxy through the leader.

    On platforms where locking isn't available, this degrades to "no lock".
    """

    path: Path
    _fp: io.TextIOWrapper | None = None

    def try_acquire(self) -> bool:
        if self._fp is not None:
            return True

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fp = open(self.path, "a+", encoding="utf-8")  # noqa: SIM115

        try:
            fp.seek(0)
            fp.truncate(0)
            fp.write(f"pid={os.getpid()}\n")
            fp.flush()
        except Exception:
            # Non-fatal.
            pass

        try:
            if sys.platform == "win32":
                import msvcrt  # type: ignore

                try:
                    msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    with contextlib.suppress(Exception):
                        fp.close()
                    return False
            else:
                import fcntl

                try:
                    fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    with contextlib.suppress(Exception):
                        fp.close()
                    return False
        except Exception:
            # If locking is not supported, fall back to "no lock".
            self._fp = fp
            return True

        self._fp = fp
        return True

    def release(self) -> None:
        fp = self._fp
        self._fp = None
        if fp is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt  # type: ignore

                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        with contextlib.suppress(Exception):
            fp.close()


def default_leader_lock() -> LeaderLock:
    return LeaderLock(path=_default_lock_path())


def rescue_leader_lock() -> LeaderLock:
    return LeaderLock(path=_rescue_lock_path())
