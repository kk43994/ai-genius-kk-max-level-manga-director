"""Identity must come from a verified official read, never a decoded access token.

The default contract was verified through browser-approved account-read OAuth.
Alternative contracts still require an explicit audited tool and subject path.
"""
import json
import logging
import re
from dataclasses import dataclass

from backend.auth.errors import AuthError
from .libtv_oauth import ISSUER, RESOURCE


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    display_name: str | None = None
    issuer: str = ISSUER
    minimal_read_verified: bool = True


class UnavailableIdentityVerifier:
    available = False

    def verify(self, tokens):
        raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')


class MCPReadSession:
    """Small Streamable HTTP session; callers must enforce tool/scope policy."""
    def __init__(self, http, access_token):
        self._http, self._token = http, access_token
        self._session = None
        self._protocol = '2025-06-18'
        self._id = 0

    def __repr__(self):
        return '<MCPReadSession credentials=redacted>'

    def _rpc(self, method, params, *, notification=False):
        self._id += 1
        payload = {'jsonrpc': '2.0', 'method': method, 'params': params}
        if not notification:
            payload['id'] = self._id
        headers = {'Authorization': 'Bearer ' + self._token,
                   'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream',
                   'MCP-Protocol-Version': self._protocol}
        if self._session:
            headers['Mcp-Session-Id'] = self._session
        result = self._http.request('POST', RESOURCE, data=json.dumps(payload).encode(), headers=headers)
        if result.status in (401, 403):
            raise AuthError('PROVIDER_AUTHORIZATION_REQUIRED')
        if result.status not in (200, 202, 204):
            logging.getLogger(__name__).error('MCP HTTP rejected: status=%s', result.status)
            raise AuthError('PROVIDER_UNAVAILABLE')
        session = next((v for k, v in result.headers.items() if k.lower() == 'mcp-session-id'), None)
        if session:
            if not isinstance(session, str) or len(session) > 512 or any(ord(c) < 33 for c in session):
                raise AuthError('PROVIDER_PROTOCOL_ERROR')
            self._session = session
        if notification:
            return {}
        if (result.data.get('id') != self._id or result.data.get('jsonrpc') != '2.0'
                or 'error' in result.data or not isinstance(result.data.get('result'), dict)):
            raise AuthError('PROVIDER_PROTOCOL_ERROR')
        return result.data['result']

    def tools(self):
        result = self._rpc('initialize', {'protocolVersion': self._protocol, 'capabilities': {},
                                         'clientInfo': {'name': 'asset-lab-customer', 'version': '0.1.0'}})
        protocol = result.get('protocolVersion')
        if protocol not in ('2025-03-26', '2025-06-18', '2025-11-25'):
            raise AuthError('PROVIDER_PROTOCOL_ERROR')
        self._protocol = protocol
        self._rpc('notifications/initialized', {}, notification=True)
        tools, cursor = [], None
        for _ in range(5):
            result = self._rpc('tools/list', {'cursor': cursor} if cursor else {})
            page = result.get('tools')
            if not isinstance(page, list) or any(not isinstance(t, dict) for t in page):
                raise AuthError('PROVIDER_PROTOCOL_ERROR')
            tools.extend(page)
            if len(tools) > 1000:
                raise AuthError('PROVIDER_PROTOCOL_ERROR')
            cursor = result.get('nextCursor')
            if not cursor:
                return tools
            if not isinstance(cursor, str) or len(cursor) > 2048:
                raise AuthError('PROVIDER_PROTOCOL_ERROR')
        raise AuthError('PROVIDER_PROTOCOL_ERROR')

    def call_tool(self, tool, arguments, *, error_code='PROVIDER_PROTOCOL_ERROR'):
        # Only audited readers or the ownership/scope-bound adapter may call this.
        result = self._rpc('tools/call', {'name': tool['name'], 'arguments': arguments})
        if result.get('isError'):
            blocks=result.get('content', [])
            text=blocks[0].get('text','') if isinstance(blocks,list) and len(blocks)==1 and isinstance(blocks[0],dict) else ''
            code = re.match(r'^Error executing tool '+re.escape(tool['name'])+r': ([A-Z][A-Z0-9_]{2,63}):', text) if isinstance(text,str) else None
            logging.getLogger(__name__).error('MCP tool returned error: tool=%s provider_code=%s',
                tool['name'], code.group(1) if code else 'UNCLASSIFIED')
            # A narrow observed preflight rejection, not an ambiguous timeout.
            if tool['name']=='create_node' and isinstance(text,str) and text.startswith('Error executing tool create_node: NODE_NAME_CONFLICT:'):
                raise AuthError('PROVIDER_NODE_NAME_CONFLICT')
            if tool['name']=='update_node' and code and code.group(1)=='SNAPSHOT_REVISION_MISMATCH':
                raise AuthError('PROVIDER_SNAPSHOT_REVISION_MISMATCH')
            raise AuthError(error_code)
        if isinstance(result.get('structuredContent'), dict):
            return result['structuredContent']
        content = result.get('content', [])
        text = [c.get('text') for c in content if isinstance(c, dict) and c.get('type') == 'text']
        try:
            if len(text) != 1:
                raise ValueError()
            result = json.loads(text[0])
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, TypeError):
            raise AuthError(error_code) from None

    def read_identity(self, tool, arguments):
        return self.call_tool(tool, arguments, error_code='PROVIDER_IDENTITY_UNAVAILABLE')


@dataclass(frozen=True)
class IdentityReadContract:
    tool_name: str
    subject_path: tuple
    display_name_path: tuple = ()
    evidence: str = ''


LIBTV_ACCOUNT_IDENTITY = IdentityReadContract(
    'account_user', ('user', 'uuid'), ('user', 'nickname'),
    'Official https://mcp.liblib.tv/mcp tools/list and account_user; '
    'browser OAuth libtv:account:read verified 2026-10-27; repeat user.uuid read matched.')


class ReadOnlyMCPIdentityVerifier:
    available = True

    def __init__(self, http, contract):
        if (not isinstance(contract, IdentityReadContract) or not contract.tool_name
                or not contract.subject_path or not contract.evidence
                or any(not isinstance(p, str) or not p for p in contract.subject_path)):
            raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')
        self._http, self._contract = http, contract

    @staticmethod
    def _path(data, path):
        for part in path:
            if not isinstance(data, dict):
                return None
            data = data.get(part)
        return data

    def read_snapshot(self, tokens):
        session = MCPReadSession(self._http, tokens['access_token'])
        matches = [t for t in session.tools() if t.get('name') == self._contract.tool_name]
        if len(matches) != 1:
            raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')
        tool = matches[0]
        annotations = tool.get('annotations') or {}
        schema = tool.get('inputSchema') or {}
        if (annotations.get('readOnlyHint') is not True
                or annotations.get('destructiveHint') is not False
                or schema.get('type') != 'object' or schema.get('required')):
            raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')
        identity = session.read_identity(tool, {})
        subject = self._path(identity, self._contract.subject_path)
        name = self._path(identity, self._contract.display_name_path) if self._contract.display_name_path else None
        if (not isinstance(subject, str) or not subject or len(subject) > 512
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in subject)):
            raise AuthError('PROVIDER_IDENTITY_UNAVAILABLE')
        return VerifiedIdentity(subject=subject, display_name=name if isinstance(name, str) else None), identity

    def verify(self, tokens):
        return self.read_snapshot(tokens)[0]
