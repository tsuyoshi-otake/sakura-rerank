"""Crash-safe byte publication helpers for one file or a related file pair."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path


class AtomicWriteError(OSError):
    """A transactional publication could not restore its pre-commit state."""


def _write_temporary_bytes(path: Path, payload: bytes, *, suffix: str = ".tmp") -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=suffix, dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        try:
            output_file = os.fdopen(descriptor, "wb")
        except BaseException:
            os.close(descriptor)
            raise
        with output_file as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _backup_existing_file(path: Path) -> Path | None:
    try:
        source = path.open("rb")
    except FileNotFoundError:
        return None

    with source:
        descriptor, backup_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".bak", dir=path.parent
        )
        backup = Path(backup_name)
        try:
            try:
                output_file = os.fdopen(descriptor, "wb")
            except BaseException:
                os.close(descriptor)
                raise
            with output_file as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
    return backup


def _remove_if_present(path: Path | None) -> None:
    if path is not None:
        path.unlink(missing_ok=True)


def write_bytes_atomic(
    path: str | Path,
    payload: bytes,
    *,
    create_parent: bool = False,
) -> None:
    """Publish bytes with one same-directory atomic replacement."""

    destination = Path(path)
    if create_parent:
        destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        temporary = _write_temporary_bytes(destination, payload)
        os.replace(temporary, destination)
        temporary = None
    finally:
        _remove_if_present(temporary)


def write_bytes_pair_atomic(
    first_path: str | Path,
    first_payload: bytes,
    second_path: str | Path,
    second_payload: bytes,
) -> None:
    """Publish two related payloads or restore the complete previous pair.

    Both payloads and both backups are fully written before the first commit.
    A failed first replacement leaves the targets untouched. A failed second
    replacement restores the already replaced first target from its backup (or
    removes it when it did not previously exist).
    """

    first = Path(first_path)
    second = Path(second_path)
    first_temporary: Path | None = None
    second_temporary: Path | None = None
    first_backup: Path | None = None
    second_backup: Path | None = None
    first_existed = False
    first_committed = False
    try:
        first_temporary = _write_temporary_bytes(first, first_payload)
        second_temporary = _write_temporary_bytes(second, second_payload)
        first_backup = _backup_existing_file(first)
        second_backup = _backup_existing_file(second)
        first_existed = first_backup is not None

        try:
            os.replace(first_temporary, first)
            first_temporary = None
            first_committed = True
            os.replace(second_temporary, second)
            second_temporary = None
        except BaseException as commit_error:
            if first_committed:
                try:
                    if first_existed:
                        assert first_backup is not None
                        os.replace(first_backup, first)
                        first_backup = None
                    else:
                        first.unlink(missing_ok=True)
                except BaseException as rollback_error:
                    raise AtomicWriteError(
                        "pair publication failed and the first artifact could not be restored"
                    ) from rollback_error
            raise commit_error
    finally:
        _remove_if_present(first_temporary)
        _remove_if_present(second_temporary)
        _remove_if_present(first_backup)
        _remove_if_present(second_backup)
