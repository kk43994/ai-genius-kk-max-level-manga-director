"""Credential-free ports used only inside the trusted backend composition."""
import copy
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .errors import GenerationError

OWNER_KEYS = ('tenantId', 'provider', 'providerAccountId', 'providerIssuer', 'providerSubject', 'spaceId', 'spaceKind')


def digest(value):
    try:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError, RecursionError):
        raise GenerationError('INPUT_INVALID') from None


def owner(value):
    if (not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k] for k in OWNER_KEYS)
            or value['provider'] != 'libtv' or value['spaceKind'] not in ('personal', 'team')):
        raise GenerationError('OWNERSHIP_MISMATCH')
    return copy.deepcopy(value)


def same_owner(a, b):
    return isinstance(a, dict) and isinstance(b, dict) and all(a.get(k) == b.get(k) for k in OWNER_KEYS)


def opaque(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}', value):
        raise GenerationError('PROVIDER_PROTOCOL_ERROR')
    return value


def safe_receipt(value):
    if not isinstance(value, dict) or not value or set(value) - {'projectId', 'taskId', 'nodeId', 'requestId'}:
        raise GenerationError('PROVIDER_RECEIPT_MISMATCH')
    return {k: opaque(v) for k, v in value.items()}


@dataclass(frozen=True, repr=False)
class AuthorizedMCP:
    """Auth supplies a fresh owner-bound callable; never a token or a global session."""
    ownership: dict
    granted_scopes: frozenset[str]
    call_tool: Callable

    def __repr__(self):
        return '<AuthorizedMCP owner-bound; credentials not accepted>'


@dataclass(frozen=True)
class ProjectBinding:
    project_id: str
    ownership: dict
    evidence: str
    verified: bool = False


@dataclass(frozen=True, repr=False)
class VerifiedReference:
    revision_id: str
    ownership: dict
    content: bytes = field(repr=False)
    mime: str
    sha256: str
    stage: str
    approved: bool = False
    stale: bool = False


@dataclass(frozen=True)
class RecipeBinding:
    """Names/aliases are configuration after discovery, not guessed model defaults."""
    model: str
    controls: Mapping[str, str] = field(default_factory=dict)
    evidence: str = ''


@dataclass(frozen=True)
class GenerationPolicy:
    allow_external_writes: bool = False
    allow_synthetic_contracts: bool = False
    max_outputs: int = 4
    max_image_bytes: int = 32 * 1024 * 1024
    max_pixels: int = 40_000_000
