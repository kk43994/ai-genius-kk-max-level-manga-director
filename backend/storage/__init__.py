"""Public module interfaces. No routes or provider clients are installed here."""
from .accounts import AccountRepository, SelectionRepository, VerifiedIdentity
from .core import SCHEMA_VERSION, Store, TenantContext, opaque_id, request_hash
from .errors import StorageError

__all__ = ["AccountRepository", "SelectionRepository", "VerifiedIdentity", "Store",
           "TenantContext", "StorageError", "SCHEMA_VERSION", "opaque_id", "request_hash"]


def register_routes(router, services):
    """Storage has no public HTTP routes; integrations inject it as services.storage."""
