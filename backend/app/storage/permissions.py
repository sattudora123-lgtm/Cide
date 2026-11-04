"""Restrict vault files to the current OS user."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

from app.storage.errors import StorageError


def restrict_to_owner(path: Path, *, is_dir: bool) -> None:
    if os.name != "nt":
        os.chmod(path, 0o700 if is_dir else 0o600)
        return
    user = os.environ.get("USERNAME")
    if not user:
        raise StorageError("Cannot determine the current user to protect data files")
    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    rights = "(OI)(CI)(F)" if is_dir else "(F)"
    result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:{rights}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise StorageError("Could not restrict data file permissions")
