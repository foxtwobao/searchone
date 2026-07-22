"""Encryption and digest helpers for stored credentials."""

from __future__ import annotations

import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    """Authenticated encryption wrapper for stored credentials."""

    def __init__(self, master_key: str):
        self._fernet = Fernet(master_key.encode("ascii"))

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str:
        if not value:
            return ""
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("stored credential cannot be decrypted") from exc


def secret_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def query_digest(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()
