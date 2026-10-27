"""Version 1 is additive and installed in one BEGIN IMMEDIATE transaction."""

STATEMENTS = [
    "CREATE TABLE settings(key TEXT PRIMARY KEY, value BLOB NOT NULL)",
    "CREATE TABLE tenants(id TEXT PRIMARY KEY, created_at TEXT NOT NULL)",
    """CREATE TABLE site_sessions(
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
        token_hash TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
        last_seen_at REAL NOT NULL, expires_at REAL NOT NULL,
        absolute_expires_at REAL NOT NULL, revoked_at REAL)""",
    "CREATE INDEX sessions_tenant ON site_sessions(tenant_id)",
    """CREATE TABLE authorization_epochs(
        tenant_id TEXT PRIMARY KEY REFERENCES tenants(id), epoch INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE records(
        tenant_id TEXT NOT NULL REFERENCES tenants(id), collection TEXT NOT NULL,
        id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0), data TEXT NOT NULL,
        immutable_fields TEXT NOT NULL, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL, reserved TEXT,
        PRIMARY KEY(tenant_id,collection,id))""",
    """CREATE TABLE secrets(
        tenant_id TEXT NOT NULL REFERENCES tenants(id), namespace TEXT NOT NULL,
        id TEXT NOT NULL, ciphertext BLOB NOT NULL,
        PRIMARY KEY(tenant_id,namespace,id))""",
    """CREATE TABLE provider_accounts(
        tenant_id TEXT NOT NULL REFERENCES tenants(id), id TEXT NOT NULL,
        provider TEXT NOT NULL, issuer TEXT, subject TEXT, display_name TEXT,
        label TEXT NOT NULL, verified INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL, expires_at REAL, last_verified_at TEXT, reason TEXT,
        version INTEGER NOT NULL CHECK(version>0), removed_at TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY(tenant_id,id))""",
    "CREATE UNIQUE INDEX provider_identity ON provider_accounts(tenant_id,provider,issuer,subject) WHERE issuer IS NOT NULL AND subject IS NOT NULL",
    """CREATE TABLE provider_spaces(
        tenant_id TEXT NOT NULL, provider_account_id TEXT NOT NULL,
        id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL, access TEXT NOT NULL,
        checked_at TEXT NOT NULL, PRIMARY KEY(tenant_id,provider_account_id,id),
        FOREIGN KEY(tenant_id,provider_account_id) REFERENCES provider_accounts(tenant_id,id))""",
    """CREATE TABLE selections(
        tenant_id TEXT PRIMARY KEY REFERENCES tenants(id),
        provider_account_id TEXT, space_id TEXT, revision INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY(tenant_id,provider_account_id) REFERENCES provider_accounts(tenant_id,id))""",
    """CREATE TABLE idempotency(
        tenant_id TEXT NOT NULL REFERENCES tenants(id), scope TEXT NOT NULL,
        key_hash TEXT NOT NULL, request_hash TEXT NOT NULL, response TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(tenant_id,scope,key_hash))""",
    """CREATE TABLE blobs(
        tenant_id TEXT NOT NULL REFERENCES tenants(id), id TEXT NOT NULL,
        sha256 TEXT NOT NULL, size INTEGER NOT NULL, mime TEXT NOT NULL,
        created_at TEXT NOT NULL, PRIMARY KEY(tenant_id,id))""",
    """CREATE TABLE leases(
        tenant_id TEXT NOT NULL REFERENCES tenants(id), resource TEXT NOT NULL,
        holder TEXT NOT NULL, fence INTEGER NOT NULL, expires_at REAL NOT NULL,
        PRIMARY KEY(tenant_id,resource))""",
]
