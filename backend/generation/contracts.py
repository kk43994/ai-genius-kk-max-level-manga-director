"""Validate exact official tools and audited response mappings; no field guessing."""
import copy
import json
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator
from .errors import GenerationError
from .types import digest


def validate(schema, value, code='INPUT_INVALID'):
    # Remote schema references must not cause network/file resolution.
    def local_only(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ('$ref', '$dynamicRef') and (not isinstance(v, str) or not v.startswith('#')):
                    raise GenerationError('PROVIDER_PROTOCOL_ERROR')
                local_only(v)
        elif isinstance(node, list):
            for v in node:
                local_only(v)
    try:
        local_only(schema)
        Draft202012Validator.check_schema(schema)
        if next(Draft202012Validator(schema).iter_errors(value), None):
            raise GenerationError(code)
    except GenerationError:
        raise
    except Exception:
        raise GenerationError(code) from None


class ToolCatalog:
    def __init__(self, tools, *, evidence):
        if not evidence or not isinstance(tools, list):
            raise GenerationError('PROVIDER_TOOL_SCHEMA_REQUIRED')
        self._tools = {}
        for tool in tools:
            name = tool.get('name')
            if not isinstance(name, str) or name in self._tools or not isinstance(tool.get('inputSchema'), dict):
                raise GenerationError('PROVIDER_TOOL_SCHEMA_REQUIRED')
            self._tools[name] = copy.deepcopy(tool)
        self.evidence = evidence

    @classmethod
    def bundled(cls):
        path = Path(__file__).with_name('contracts') / 'libtv-tools-public-2026-10-27.json'
        data = json.loads(path.read_text())
        return cls(data['tools'], evidence=data['source'])

    def tool(self, name):
        if name not in self._tools:
            raise GenerationError('PROVIDER_TOOL_SCHEMA_REQUIRED', missing=name)
        return copy.deepcopy(self._tools[name])

    def scopes(self, name):
        schemes = self.tool(name).get('_meta', {}).get('securitySchemes')
        if not isinstance(schemes, list) or len(schemes) != 1 or schemes[0].get('type') != 'oauth2':
            raise GenerationError('PROVIDER_TOOL_SCHEMA_REQUIRED', missing=name + '.securitySchemes')
        scopes = schemes[0].get('scopes')
        if not isinstance(scopes, list) or not scopes or any(not isinstance(s, str) for s in scopes):
            raise GenerationError('PROVIDER_TOOL_SCHEMA_REQUIRED', missing=name + '.scopes')
        return frozenset(scopes)

    def request(self, name, arguments):
        validate(self.tool(name)['inputSchema'], arguments)

    def response(self, name, result):
        if not isinstance(result, dict):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR')
        if result.get('isError'):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR')
        if 'structuredContent' in result:
            body = result['structuredContent']
        else:
            blocks = result.get('content')
            texts = [x.get('text') for x in blocks or [] if isinstance(x, dict) and x.get('type') == 'text']
            try:
                if len(texts) != 1 or not isinstance(texts[0], str) or len(texts[0]) > 4 * 1024 * 1024:
                    raise ValueError()
                body = json.loads(texts[0])
            except (ValueError, TypeError):
                raise GenerationError('PROVIDER_PROTOCOL_ERROR') from None
        if not isinstance(body, dict):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR')
        try:
            if len(json.dumps(body, allow_nan=False)) > 4 * 1024 * 1024:
                raise ValueError()
        except (ValueError, TypeError, RecursionError):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR') from None
        schema = self.tool(name).get('outputSchema')
        if schema:
            validate(schema, body, 'PROVIDER_PROTOCOL_ERROR')
        return body

    def fingerprint(self, name):
        return digest(self.tool(name))


@dataclass(frozen=True)
class ResponseContract:
    """Configured from observed/official structured responses, never from a browser.

    Generic outputSchema type=object alone does not establish concrete paths.
    Synthetic contracts are allowed only with the explicit offline test policy.
    """
    tool: str
    schema: dict
    fields: dict[str, tuple]
    evidence: str
    verified: bool = False
    synthetic: bool = False
    states: dict[str, str] = field(default_factory=dict)

    def read(self, body, name):
        validate(self.schema, body, 'PROVIDER_PROTOCOL_ERROR')
        return self.leaf(body, name)

    def leaf(self, body, name):
        """Extract from an item of an already schema-validated parent response."""
        if name not in self.fields:
            raise GenerationError('PROVIDER_RESPONSE_CONTRACT_REQUIRED', missing=self.tool + '.' + name)
        value = body
        try:
            for part in self.fields[name]:
                value = value[part]
        except (KeyError, IndexError, TypeError):
            raise GenerationError('PROVIDER_PROTOCOL_ERROR') from None
        return value


class ResponseContracts:
    def __init__(self, contracts=()):
        self._items = {c.tool: c for c in contracts}

    def require(self, tool, policy, fields=()):
        item = self._items.get(tool)
        if (not item or not item.evidence or (not item.verified and not (item.synthetic and policy.allow_synthetic_contracts))
                or item.synthetic and not policy.allow_synthetic_contracts):
            raise GenerationError('PROVIDER_RESPONSE_CONTRACT_REQUIRED', missing=tool)
        for name in fields:
            if name not in item.fields:
                raise GenerationError('PROVIDER_RESPONSE_CONTRACT_REQUIRED', missing=tool + '.' + name)
        return item
