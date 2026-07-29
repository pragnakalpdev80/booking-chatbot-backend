"""Model fields with at-rest encryption.

``EncryptedTextField`` keeps sensitive values (e.g. third-party OAuth tokens)
encrypted in the database while behaving like a plain ``TextField`` in Python:
assign/read the cleartext, and only a Fernet token ever touches the column.
"""

from __future__ import annotations

from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.expressions import Combinable


class EncryptedTextField(models.TextField):
    """A ``TextField`` transparently encrypted at rest with Fernet.

    Fernet provides authenticated symmetric encryption (AES-128-CBC + HMAC); a DB
    read yields only an opaque token, so a database compromise does not expose the
    cleartext. The cleartext exists solely in process memory.

    The key comes from ``settings.FIELD_ENCRYPTION_KEY`` (a urlsafe-base64 32-byte
    key, e.g. ``Fernet.generate_key()``). It is resolved lazily, so importing the
    field — and migrations that merely reference its type — never require the key;
    only an actual encrypt/decrypt does, and a missing key fails fast rather than
    silently storing cleartext.

    Empty values (``None``/``""``) are stored as-is, so ``blank``/``default=""``
    columns are unaffected. Because Fernet uses a random IV, the ciphertext is
    non-deterministic — these fields must never be used in a ``WHERE`` lookup by
    value (they are write/read-by-key only).
    """

    @staticmethod
    def _fernet() -> Fernet:
        key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
        if not key:
            raise ImproperlyConfigured(
                "FIELD_ENCRYPTION_KEY must be set to use an EncryptedTextField."
            )
        return Fernet(key.encode() if isinstance(key, str) else key)

    def get_prep_value(self, value: Any) -> Any:
        prepared = super().get_prep_value(value)
        if prepared is None or prepared == "" or isinstance(prepared, Combinable):
            return prepared
        return self._fernet().encrypt(str(prepared).encode()).decode()

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> str | None:
        if value is None or value == "":
            return value
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except InvalidToken as exc:
            # Cleartext/corrupted data left over from before encryption was enabled —
            # surface loudly rather than handing back a mangled value.
            raise ValueError(
                "Stored value is not a valid encrypted token; was it written before "
                "FIELD_ENCRYPTION_KEY / EncryptedTextField was in place?"
            ) from exc
