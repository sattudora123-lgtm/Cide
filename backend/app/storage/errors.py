class StorageError(Exception):
    """A storage failure whose message is safe to surface."""


class StorageIntegrityError(StorageError):
    """Ciphertext, manifest, or collection set failed authentication."""
