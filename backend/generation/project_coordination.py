"""Serialize local canvas mutations around revision-bound submissions.

This only coordinates this process. Official revision checks still protect
against remote editors and asynchronous changes; rejection never auto-retries.
"""
from contextlib import contextmanager
from threading import Lock, RLock
from weakref import WeakValueDictionary

_guard = Lock()
_locks = WeakValueDictionary()


@contextmanager
def project_mutation(ownership, project):
    key = (ownership['tenantId'], ownership['providerAccountId'], ownership['spaceId'], project)
    with _guard:
        lock = _locks.get(key)
        if lock is None:
            lock = RLock()
            _locks[key] = lock
    with lock:
        yield
