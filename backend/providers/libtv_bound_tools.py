"""Narrow, credential-free interface for an injected server-side operation adapter.

The adapter still has to prove project -> account/space ownership using the
official project response before any project operation. This transport never
changes the remote active account or invents an account/team request parameter.
"""
import copy

from backend.auth.errors import AuthError
from .libtv_identity import MCPReadSession
from .libtv_oauth import SCOPES


class BoundMCPTools:
    def __init__(self, service, ctx, ownership):
        self._service, self._ctx, self._owner = service, copy.copy(ctx), copy.deepcopy(ownership)
        self._session = None
        self._catalog = None
        self._access_token = None

    def __repr__(self):
        return '<BoundMCPTools credentials=redacted>'

    def list_tools(self):
        bundle, _ = self._service._bundle_for(self._ctx, self._owner)
        result = MCPReadSession(self._service.oauth.http, bundle['tokens']['access_token']).tools()
        self._service._bundle_for(self._ctx, self._owner)
        return result

    def call_tool(self, name, arguments, *, space_id):
        if (space_id != self._owner['spaceId'] or not isinstance(name, str)
                or not isinstance(arguments, dict)):
            raise AuthError('OWNERSHIP_MISMATCH')
        bundle, _ = self._service._bundle_for(self._ctx, self._owner)
        token = bundle['tokens']['access_token']
        if self._session is None or self._access_token != token:
            self._session = MCPReadSession(self._service.oauth.http, token)
            self._catalog = self._session.tools()
            self._access_token = token
        session = self._session
        matches = [tool for tool in self._catalog if tool.get('name') == name]
        if len(matches) != 1:
            raise AuthError('PROVIDER_CAPABILITY_UNAVAILABLE')
        tool = matches[0]
        metadata = tool.get('_meta')
        schemes = metadata.get('securitySchemes') if isinstance(metadata, dict) else None
        if not isinstance(schemes, list) or len(schemes) > 20:
            raise AuthError('PROVIDER_SCOPE_UNAVAILABLE')
        required = [set(s.get('scopes', [])) for s in schemes
                    if isinstance(s, dict) and s.get('type') == 'oauth2'
                    and isinstance(s.get('scopes'), list)
                    and all(isinstance(scope, str) for scope in s['scopes'])]
        granted = set(bundle['tokens'].get('scope', '').split())
        candidates = [scopes for scopes in required if scopes and scopes <= SCOPES and scopes <= granted]
        if not candidates:
            raise AuthError('PROVIDER_SCOPE_UNAVAILABLE')
        annotations = tool.get('annotations')
        if not isinstance(annotations, dict):
            raise AuthError('PROVIDER_SCOPE_UNAVAILABLE')
        readonly = annotations.get('readOnlyHint')
        if (type(readonly) is not bool
                or (not readonly and not any(any(s.endswith(':write') for s in scopes) for scopes in candidates))):
            raise AuthError('PROVIDER_SCOPE_UNAVAILABLE')
        account_tool = next((t for t in self._catalog if t.get('name') == 'account_user'), None)
        snapshot = None
        if (callable(getattr(getattr(self._service, 'account_reader', None), 'spaces_from_payload', None))
                and callable(getattr(self._service, '_assert_space_payload', None))
                and account_tool and account_tool.get('annotations', {}).get('readOnlyHint') is True
                and 'libtv:account:read' in granted):
            snapshot = session.call_tool(account_tool, {})
            self._service._assert_space_payload(self._ctx, self._owner, snapshot)
        else:
            self._service._assert_space(self._ctx, self._owner)
        # Check local revocation again after the live membership response and
        # before invoking a mutation. Session reuse never caches membership.
        self._service._bundle_for(self._ctx, self._owner)
        if (snapshot is not None and not readonly and self._owner.get('spaceKind') == 'personal'
                and str(snapshot.get('activeAccountId')) != self._owner['spaceId']):
            raise AuthError('OWNERSHIP_MISMATCH')
        result = snapshot if name == 'account_user' and arguments == {} and snapshot is not None else session.call_tool(tool, copy.deepcopy(arguments))
        self._service._bundle_for(self._ctx, self._owner)
        return result
