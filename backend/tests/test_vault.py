import json
import os
import subprocess

import pytest

from app.storage.errors import StorageIntegrityError
from app.storage.vault import EncryptedJsonStore


def _store(tmp_path):
    store = EncryptedJsonStore(tmp_path / "vault", os.urandom(32))
    store.initialize()
    return store


def _snapshot(store):
    with store.transaction() as database:
        return json.loads(json.dumps(database))


def test_files_are_encrypted_and_round_trip(tmp_path):
    store = _store(tmp_path)
    email = "plaintext-sentinel-email@example.com"
    password = "plaintext-sentinel-password-value"
    with store.transaction() as database:
        database["users"].append({"id": "1", "email": email, "password": password})
    raw = b"".join(path.read_bytes() for path in store.directory.rglob("*") if path.is_file())
    assert email.encode() not in raw
    assert password.encode() not in raw
    assert raw.startswith(b"CIDE") or (store.directory / "users.enc").read_bytes().startswith(b"CIDE")
    with store.transaction() as database:
        assert database["users"] == [{"id": "1", "email": email, "password": password}]
    assert not list(store.directory.glob("*.tmp"))


def test_ciphertext_changes_when_data_changes(tmp_path):
    store = _store(tmp_path)
    first = (store.directory / "meta.enc").read_bytes()
    with store.transaction() as database:
        database["meta"]["event_seq"] = 1
    second = (store.directory / "meta.enc").read_bytes()
    assert first != second


def test_wrong_key_and_tampering_fail(tmp_path):
    store = _store(tmp_path)
    with store.transaction() as database:
        database["tasks"].append({"id": "task-1"})
    other = EncryptedJsonStore(store.directory, os.urandom(32))
    with pytest.raises(StorageIntegrityError):
        with other.transaction():
            pass
    target = store.directory / "tasks.enc"
    blob = bytearray(target.read_bytes())
    blob[-1] ^= 0x01
    target.write_bytes(blob)
    with pytest.raises(StorageIntegrityError):
        with store.transaction():
            pass


def test_committed_stage_is_recovered_and_incomplete_stage_is_discarded(tmp_path):
    store = _store(tmp_path)
    with store.transaction() as database:
        database["users"].append({"id": "1", "email": "a@example.com"})
    original = _snapshot(store)
    updated = json.loads(json.dumps(original))
    updated["users"].append({"id": "2", "email": "b@example.com"})
    store.stage_without_promote(updated)
    (store.directory / "users.enc").unlink()
    with store.transaction() as database:
        assert [item["id"] for item in database["users"]] == ["1", "2"]

    current = _snapshot(store)
    extra = json.loads(json.dumps(current))
    extra["users"].append({"id": "9", "email": "nope@example.com"})
    store.stage_incomplete(extra)
    with store.transaction() as database:
        assert [item["id"] for item in database["users"]] == ["1", "2"]
    assert not store.directory.joinpath(".staging").exists()


def test_directory_acl_does_not_grant_everyone(tmp_path):
    store = _store(tmp_path)
    if os.name != "nt":
        mode = (store.directory / "users.enc").stat().st_mode
        assert mode & 0o077 == 0
        return
    result = subprocess.run(
        ["icacls", str(store.directory)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Everyone" not in result.stdout
    assert "BUILTIN\\Users" not in result.stdout
