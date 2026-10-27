"""Small integration ports; shared storage/auth modules supply implementations.

Transactions must be durable and serialize writers across processes. All methods
are tenant scoped using the authenticated ctx, never a browser supplied tenant.
See README.md for exact provider/validation payloads and crash guarantees.
"""

from dataclasses import dataclass, field
from typing import Any, ContextManager, Mapping, Protocol


@dataclass(frozen=True)
class TaskPolicy:
    confirmation_key: bytes = field(repr=False)
    allow_paid_submission: bool = False
    video_generation: bool = False
    confirmation_ttl_seconds: int = 600
    lease_seconds: int = 180
    max_output_bytes: int = 32 * 1024 * 1024
    max_outputs: int = 4


@dataclass(frozen=True)
class DownloadArtifact:
    content: bytes
    mime: str
    # Optional official checksum. A local checksum is always calculated and
    # verified again by reading the persisted blob before marking completed.
    sha256: str | None = None


class TaskTransaction(Protocol):
    def assert_selection(self, expected_revision: int, ownership: dict | None = None) -> None: ...
    def get_task(self, task_id: str) -> dict | None: ...
    def put_task(self, task: dict, expected_version: int | None) -> None: ...
    def list_tasks(self) -> list[dict]: ...
    def get_request(self, scope: str, key_digest: str) -> dict | None: ...
    def put_request(self, scope: str, key_digest: str, record: dict) -> None: ...


class TaskRepository(Protocol):
    def transaction(self, ctx: Any) -> ContextManager[TaskTransaction]: ...


class InputValidator(Protocol):
    def validate_task_inputs(self, ctx: Any, spec: dict, ownership: dict) -> Mapping: ...


class SelectionService(Protocol):
    def get_selection(self, ctx: Any) -> Mapping: ...


class ProviderService(Protocol):
    def get_account(self, ctx: Any, account_id: str) -> Mapping: ...
    def client_for(self, ctx: Any, ownership: dict) -> Any: ...


class OutputStore(Protocol):
    def put(self, ctx: Any, *, task_id: str, ownership: dict, index: int,
            content: bytes, mime: str, sha256: str) -> Mapping: ...
    def read(self, ctx: Any, blob_id: str) -> bytes: ...
