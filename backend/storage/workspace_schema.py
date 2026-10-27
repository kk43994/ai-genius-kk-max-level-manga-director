"""Additive v1 -> v2 migration: no owner is inferred from old provider accounts."""

STATEMENTS_V2 = [
    """CREATE TABLE workspace_owners(
        tenant_id TEXT PRIMARY KEY REFERENCES tenants(id), provider TEXT NOT NULL,
        issuer TEXT NOT NULL, subject TEXT NOT NULL, label TEXT NOT NULL,
        bound_at TEXT NOT NULL, authorization_attempt_id TEXT NOT NULL UNIQUE)""",
    "CREATE INDEX workspace_owner_identity ON workspace_owners(provider,issuer,subject)",
    """CREATE TRIGGER immutable_workspace_owner BEFORE UPDATE OF tenant_id,provider,issuer,subject
        ON workspace_owners BEGIN SELECT RAISE(ABORT,'workspace owner is immutable'); END""",
    """CREATE TRIGGER retain_workspace_owner BEFORE DELETE ON workspace_owners
        BEGIN SELECT RAISE(ABORT,'workspace owner must not be removed implicitly'); END""",
    """CREATE TABLE workspace_intents(
        id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL REFERENCES tenants(id),
        site_session_id TEXT NOT NULL REFERENCES site_sessions(id),
        oauth_attempt_id TEXT NOT NULL UNIQUE, nonce_hash TEXT NOT NULL,
        state_hash TEXT NOT NULL, purpose TEXT NOT NULL,
        status TEXT NOT NULL, version INTEGER NOT NULL,
        created_at REAL NOT NULL, expires_at REAL NOT NULL, data TEXT NOT NULL)""",
    "CREATE INDEX workspace_intents_session ON workspace_intents(tenant_id,site_session_id,status)",
    """CREATE TABLE workspace_content_revisions(
        tenant_id TEXT PRIMARY KEY REFERENCES tenants(id), revision INTEGER NOT NULL)""",
]

# Include current records in the snapshot checks; triggers track subsequent writes
# from any module, including the auth module's direct SQL projection updates.
for table in ("records", "blobs", "provider_accounts", "provider_spaces", "selections"):
    for action, source in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
        STATEMENTS_V2.append(f"""CREATE TRIGGER workspace_revision_{table}_{action.lower()}
            AFTER {action} ON {table} BEGIN
            INSERT INTO workspace_content_revisions(tenant_id,revision) VALUES({source}.tenant_id,1)
            ON CONFLICT(tenant_id) DO UPDATE SET revision=revision+1;
            END""")
