"""Server-side AEAD with explicit keys; never generate an ephemeral production key.

The storage module persists ciphertext only. Keys must come from the deployment's
secret configuration, outside the database/backup/release. Additional keys permit
reading older records during a deliberate rotation.
"""
import base64
import json
import re
import secrets

from .errors import AuthError


class AesGcmSecretCodec:
    def __init__(self, keys, active_key):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            if active_key not in keys or not keys:
                raise ValueError()
            if any(not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', k)
                   or not isinstance(v, bytes) or len(v) != 32 for k, v in keys.items()):
                raise ValueError()
            self._keys = {k: AESGCM(v) for k, v in keys.items()}
            self._active = active_key
        except (ImportError, ValueError, TypeError):
            raise AuthError('SECRET_STORAGE_UNAVAILABLE') from None

    def seal(self, value, *, binding):
        try:
            nonce = secrets.token_bytes(12)
            clear = json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()
            encrypted = self._keys[self._active].encrypt(nonce, clear, binding.encode())
            encoded = base64.urlsafe_b64encode(nonce + encrypted).decode()
            return f'v1.{self._active}.{encoded}'
        except Exception:
            raise AuthError('SECRET_STORAGE_UNAVAILABLE') from None

    def open(self, value, *, binding):
        try:
            version, key_id, encoded = value.split('.', 2)
            if version != 'v1' or len(encoded) > 200000:
                raise ValueError()
            encrypted = base64.b64decode(encoded, altchars=b'-_', validate=True)
            clear = self._keys[key_id].decrypt(encrypted[:12], encrypted[12:], binding.encode())
            result = json.loads(clear)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except Exception:
            raise AuthError('SECRET_STORAGE_UNAVAILABLE') from None

    def __repr__(self):
        return '<AesGcmSecretCodec keys=redacted>'
