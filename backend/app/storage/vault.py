"""Encrypted JSON collections with an atomic staging commit.

Each collection is JSON encrypted with AES-256-GCM. A manifest stores the
generation and the SHA-256 of every ciphertext file. A commit is written into
`.staging`, authenticated, then promoted with per-file replaces. Plaintext is
never written to disk. If the process stops after staging, the next open
finishes the promote. An incomplete or unreadable stage is discarded.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.core.errors import CommitAndRaise
from app.storage.crypto import decrypt, encrypt
from app.storage.errors import StorageError, StorageIntegrityError
from app.storage.permissions import restrict_to_owner
from app.storage.schema import COLLECTIONS, empty_db

MANIFEST = "manifest.enc"
COMMITTED = "COMMITTED"
_FILE_NAMES = tuple(f"{name}.enc" for name in COLLECTIONS) + ("meta.enc",)


def _canonical(database: dict) -> str:
    return json.dumps(database, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _collection_aad(name: str, generation: int) -> bytes:
    return f"cide-collection:{name}:{generation}".encode("ascii")


def _fsync_dir(directory: Path) -> None:
    try:
        handle = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(handle)
    except OSError:
        return
    finally:
        os.close(handle)


def _replace(source: Path, target: Path) -> None:
    last_error: OSError | None = None
    for _ in range(5):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise StorageError("Could not commit an encrypted data file") from last_error


def _write_bytes(path: Path, data: bytes) -> None:
    temporary = path.parent / f"{path.name}.tmp"
    with open(temporary, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    _replace(temporary, path)


class EncryptedJsonStore:
    def __init__(self, directory: Path, key: bytes):
        if len(key) != 32:
            raise StorageError("Data encryption key must be 32 bytes")
        self.directory = directory
        self._key = key
        self._thread_lock = threading.Lock()
        self._staging = directory / ".staging"
        self._lock_path = directory / ".lock"

    def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        restrict_to_owner(self.directory, is_dir=True)
        with self._thread_lock, self._file_lock():
            self._recover_unlocked()
            if not (self.directory / MANIFEST).exists():
                self._commit_unlocked(empty_db())

    @contextmanager
    def transaction(self) -> Iterator[dict]:
        """Yield the database. Write it back only when the caller changed it.

        Do not open another transaction inside this block, and do not await
        while it is open. The file lock is held for the duration.
        """
        with self._thread_lock, self._file_lock():
            self._recover_unlocked()
            database = self._load_unlocked()
            before = _canonical(database)
            try:
                yield database
            except CommitAndRaise:
                if _canonical(database) != before:
                    self._commit_unlocked(database)
                raise
            except Exception:
                raise
            else:
                if _canonical(database) != before:
                    self._commit_unlocked(database)

    def stage_without_promote(self, database: dict) -> None:
        """Test seam. Writes a valid staged commit and does not touch live files."""
        with self._thread_lock, self._file_lock():
            self._recover_unlocked()
            self._stage_unlocked(database, mark_committed=True)

    def stage_incomplete(self, database: dict) -> None:
        """Test seam. Writes a stage that recovery must discard."""
        with self._thread_lock, self._file_lock():
            self._recover_unlocked()
            self._stage_unlocked(database, mark_committed=False)

    def _commit_unlocked(self, database: dict) -> None:
        self._stage_unlocked(database, mark_committed=True)
        self._promote_unlocked()

    def _stage_unlocked(self, database: dict, *, mark_committed: bool) -> None:
        if self._staging.exists():
            shutil.rmtree(self._staging)
        self._staging.mkdir(parents=True)
        restrict_to_owner(self._staging, is_dir=True)
        generation = int(database.get("meta", {}).get("generation", 0)) + 1
        database.setdefault("meta", {})
        database["meta"]["generation"] = generation
        hashes: dict[str, str] = {}
        for name in COLLECTIONS:
            raw = _dump(database[name])
            blob = encrypt(self._key, raw, aad=_collection_aad(name, generation))
            _write_bytes(self._staging / f"{name}.enc", blob)
            hashes[f"{name}.enc"] = hashlib.sha256(blob).hexdigest()
        meta_blob = encrypt(self._key, _dump(database["meta"]), aad=_collection_aad("meta", generation))
        _write_bytes(self._staging / "meta.enc", meta_blob)
        hashes["meta.enc"] = hashlib.sha256(meta_blob).hexdigest()
        manifest = {"generation": generation, "files": hashes}
        manifest_blob = encrypt(self._key, _dump(manifest), aad=b"cide-manifest")
        _write_bytes(self._staging / MANIFEST, manifest_blob)
        if mark_committed:
            _write_bytes(self._staging / COMMITTED, b"ok")
        _fsync_dir(self._staging)

    def _promote_unlocked(self) -> None:
        # Copy, do not move. A crash mid-promote leaves the stage intact so the
        # next open can finish the same commit before any read is served.
        self._verify_dir(self._staging)
        for name in (*_FILE_NAMES, MANIFEST):
            _write_bytes(self.directory / name, (self._staging / name).read_bytes())
        shutil.rmtree(self._staging)
        _fsync_dir(self.directory)

    def _recover_unlocked(self) -> None:
        for temporary in self.directory.glob("*.tmp"):
            temporary.unlink(missing_ok=True)
        if not self._staging.exists():
            return
        if not (self._staging / COMMITTED).exists():
            shutil.rmtree(self._staging, ignore_errors=True)
            return
        try:
            self._verify_dir(self._staging)
        except StorageIntegrityError:
            shutil.rmtree(self._staging, ignore_errors=True)
            return
        self._promote_unlocked()

    def _verify_dir(self, directory: Path) -> None:
        manifest = self._read_manifest(directory)
        generation = int(manifest["generation"])
        files: dict[str, str] = manifest["files"]
        if set(files) != set(_FILE_NAMES):
            raise StorageIntegrityError("Encrypted manifest does not match the collection set")
        for name, digest in files.items():
            path = directory / name
            if not path.is_file():
                raise StorageIntegrityError("Encrypted collection is missing")
            blob = path.read_bytes()
            if hashlib.sha256(blob).hexdigest() != digest:
                raise StorageIntegrityError("Encrypted collection hash mismatch")
            decrypt(self._key, blob, aad=_collection_aad(name[:-4], generation))

    def _read_manifest(self, directory: Path) -> dict:
        path = directory / MANIFEST
        if not path.is_file():
            raise StorageIntegrityError("Encrypted manifest is missing")
        try:
            payload = json.loads(decrypt(self._key, path.read_bytes(), aad=b"cide-manifest"))
        except StorageIntegrityError:
            raise
        except Exception as exc:
            raise StorageIntegrityError("Encrypted manifest could not be read") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("files"), dict):
            raise StorageIntegrityError("Encrypted manifest has an unexpected shape")
        if not isinstance(payload.get("generation"), int):
            raise StorageIntegrityError("Encrypted manifest has an unexpected shape")
        return payload

    def _load_unlocked(self) -> dict:
        manifest_path = self.directory / MANIFEST
        if not manifest_path.exists():
            return empty_db()
        manifest = self._read_manifest(self.directory)
        generation = int(manifest["generation"])
        files: dict[str, str] = manifest["files"]
        if set(files) != set(_FILE_NAMES):
            raise StorageIntegrityError("Encrypted manifest does not match the collection set")
        database = empty_db()
        for name, digest in files.items():
            path = self.directory / name
            if not path.is_file():
                raise StorageIntegrityError("Encrypted collection is missing")
            blob = path.read_bytes()
            if hashlib.sha256(blob).hexdigest() != digest:
                raise StorageIntegrityError("Encrypted collection hash mismatch")
            try:
                payload = json.loads(decrypt(self._key, blob, aad=_collection_aad(name[:-4], generation)))
            except StorageIntegrityError:
                raise
            except Exception as exc:
                raise StorageIntegrityError("Encrypted collection could not be read") from exc
            database[name[:-4]] = payload
        self._validate_shape(database)
        database["meta"]["generation"] = generation
        return database

    def _validate_shape(self, database: dict) -> None:
        for name in COLLECTIONS:
            if not isinstance(database.get(name), list):
                raise StorageIntegrityError("Encrypted collection has an unexpected shape")
        meta = database.get("meta")
        if not isinstance(meta, dict) or not isinstance(meta.get("event_seq"), int):
            raise StorageIntegrityError("Encrypted collection has an unexpected shape")
        if meta["event_seq"] < 0 or not isinstance(meta.get("generation"), int):
            raise StorageIntegrityError("Encrypted collection has an unexpected shape")

    @contextmanager
    def _file_lock(self) -> Iterator[None]:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._lock_path, "a+b")
        try:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                locked = False
                for _ in range(50):
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        locked = True
                        break
                    except OSError:
                        time.sleep(0.05)
                if not locked:
                    raise StorageError("Could not lock the data directory")
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _dump(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
