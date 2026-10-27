"""Bridge to the stable account projection, verified against Store schema v2.

provider_accounts is the authoritative public projection used by selections.
Attempt/client/refresh data and usable grants live only in Store's encrypted
secrets. The entire callback commit, account projection and grant are one SQLite
transaction. The narrow schema bridge uses tx._conn until storage exposes an
equivalent in-transaction account API; all SQL is explicitly tenant constrained.
"""
import copy
import json
from contextlib import contextmanager

from .errors import AuthError, require_context
from .service import utc


class StorageAuthRepository:
    def __init__(self, store):
        self.store = store

    @staticmethod
    def _secret(tx, namespace, id):
        try:
            return tx.secret_get(namespace, id)
        except Exception as err:
            if getattr(err, 'code', None) == 'NOT_FOUND':
                return None
            raise

    @contextmanager
    def transaction(self, ctx):
        tenant, _ = require_context(ctx, allow_worker=True)
        with self.store.transaction(ctx) as tx:
            tx._check(write=True)
            if tx.tenant_id != tenant:
                raise AuthError('NOT_FOUND')
            state = self._secret(tx, 'libtv-oauth', 'state') or {
                'tenantId': tenant, 'schemaVersion': 1, 'attempts': {}}
            original_meta = copy.deepcopy(state)
            accounts = {}
            for row in tx._conn.execute("SELECT * FROM provider_accounts WHERE tenant_id=? AND provider='libtv'", (tenant,)):
                secret = self._secret(tx, 'provider-grants', row['id']) or {}
                accounts[row['id']] = {'id': row['id'], 'version': row['version'], 'label': row['label'],
                    'identity': {'issuer': row['issuer'], 'subject': row['subject'],
                                 'displayName': row['display_name'], 'verified': bool(row['verified'])},
                    'authorizationState': row['state'], 'expiresAtEpoch': row['expires_at'],
                    'lastVerifiedAt': row['last_verified_at'], 'removedAt': row['removed_at'], 'reason': row['reason'],
                    'private': secret.get('authBundleCiphertext'), 'refreshClaim': secret.get('refreshClaim'),
                    'grantedScopes': secret.get('grantedScopes', [])}
            original_accounts = copy.deepcopy(accounts)
            state['accounts'] = accounts
            yield state
            for id, account in state['accounts'].items():
                before = original_accounts.get(id)
                if account == before:
                    continue
                identity = account['identity']
                if before and (identity['issuer'] != before['identity']['issuer'] or
                               identity['subject'] != before['identity']['subject']):
                    # Unverified placeholders may be completed, verified identities never change.
                    if before['identity']['verified']:
                        raise AuthError('PROVIDER_IDENTITY_MISMATCH')
                values = (identity['issuer'], identity['subject'], identity['displayName'], account['label'],
                          int(identity['verified']), account['authorizationState'], account['expiresAtEpoch'],
                          account['lastVerifiedAt'], account['reason'], account['version'], account['removedAt'])
                now = utc(self.store.clock())
                if before:
                    tx._conn.execute('''UPDATE provider_accounts SET issuer=?,subject=?,display_name=?,label=?,
                        verified=?,state=?,expires_at=?,last_verified_at=?,reason=?,version=?,removed_at=?,updated_at=?
                        WHERE tenant_id=? AND id=? AND version=?''', values + (now, tenant, id, before['version']))
                else:
                    tx._conn.execute('''INSERT INTO provider_accounts
                        (issuer,subject,display_name,label,verified,state,expires_at,last_verified_at,reason,version,
                         removed_at,created_at,updated_at,tenant_id,id,provider)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'libtv')''', values + (now, now, tenant, id))
                if account['private']:
                    tx.secret_put('provider-grants', id, {'authBundleCiphertext': account['private'],
                                                         'refreshClaim': account.get('refreshClaim'),
                                                         'grantedScopes': account.get('grantedScopes', [])})
                else:
                    tx.secret_delete('provider-grants', id)
                if account['removedAt'] and (not before or not before['removedAt']):
                    tx._conn.execute("UPDATE provider_spaces SET access='revoked' WHERE tenant_id=? AND provider_account_id=?", (tenant, id))
                    tx._conn.execute('''UPDATE selections SET provider_account_id=NULL,space_id=NULL,revision=revision+1
                        WHERE tenant_id=? AND provider_account_id=?''', (tenant, id))
            if set(original_accounts) - set(state['accounts']):
                raise AuthError('PROVIDER_PROTOCOL_ERROR')  # Tombstones are retained.
            meta = {k: v for k, v in state.items() if k != 'accounts'}
            if meta != original_meta:
                tx.secret_put('libtv-oauth', 'state', meta)

    def affected_task_ids(self, ctx, id):
        with self.store.transaction(ctx, readonly=True) as tx:
            rows = tx._conn.execute("SELECT id,data FROM records WHERE tenant_id=? AND collection='tasks'", (tx.tenant_id,))
            return [row['id'] for row in rows if json.loads(row['data']).get('ownership', {}).get('providerAccountId') == id]
