"""Project official account_user membership into the v1 space-list contract.

The live response supplies accounts.accounts, accountId and accountName.
The official web application's account hook verifies accountType 1=personal,
2=team (evidence in backend/auth/OFFICIAL_READ_EVIDENCE.md). Nothing here
changes the remote active account, derives a team ID, or grants task permission.
"""
from datetime import datetime, timezone

from backend.auth.errors import AuthError
from .libtv_identity import LIBTV_ACCOUNT_IDENTITY, ReadOnlyMCPIdentityVerifier


class LibTVAccountReader:
    available = True

    def __init__(self, http, *, clock):
        self._reader = ReadOnlyMCPIdentityVerifier(http, LIBTV_ACCOUNT_IDENTITY)
        self._clock = clock

    def list_spaces(self, tokens, *, expected_subject):
        identity, payload = self._reader.read_snapshot(tokens)
        if identity.subject != expected_subject:
            raise AuthError('PROVIDER_IDENTITY_MISMATCH')
        accounts = payload.get('accounts')
        rows = accounts.get('accounts') if isinstance(accounts, dict) else None
        if not isinstance(rows, list) or len(rows) > 1000:
            raise AuthError('PROVIDER_PROTOCOL_ERROR')
        checked_at = datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        result, seen = [], set()
        for row in rows:
            if not isinstance(row, dict):
                raise AuthError('PROVIDER_PROTOCOL_ERROR')
            account_id, account_type, name = row.get('accountId'), row.get('accountType'), row.get('accountName')
            if (type(account_id) is not int or account_id <= 0 or account_id in seen
                    or not isinstance(name, str) or not name.strip() or len(name) > 256
                    or any(ord(c) < 32 or ord(c) == 127 for c in name)):
                raise AuthError('PROVIDER_PROTOCOL_ERROR')
            if type(account_type) is not int or account_type not in (1, 2):
                # Do not silently label a future/unknown account type as personal.
                raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE')
            if account_type == 1 and row.get('ownerUuid') != identity.subject:
                raise AuthError('PROVIDER_IDENTITY_MISMATCH')
            seen.add(account_id)
            result.append({'id': str(account_id), 'kind': 'personal' if account_type == 1 else 'team',
                'name': name, 'access': 'available', 'checkedAt': checked_at})
        # Membership is not a paid-generation entitlement. isActive selects the
        # remote UI account; memberAccount describes a plan, never a balance.
        return {'items': result, 'nextCursor': None}
