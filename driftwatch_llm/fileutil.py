"""Small file helpers: private (owner-only) atomic writes."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_POSIX = os.name == "posix"


def write_private(path: Path, text: str) -> None:
    """Write `text` to `path` atomically, readable only by the current user (POSIX: 0600, dir 0700).

    On Windows the file inherits the user profile ACL, which is owner-only by default.
    """
    path = Path(path)
    parent = path.parent
    created = not parent.exists()
    parent.mkdir(parents=True, exist_ok=True)
    if created and _POSIX:
        os.chmod(parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if _POSIX:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
