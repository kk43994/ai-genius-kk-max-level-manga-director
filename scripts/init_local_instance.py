#!/usr/bin/env python3
"""Provision a separate local development data/key layout. Never overwrite a key."""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    directory = args.directory
    if not directory.is_absolute() or directory.resolve().is_relative_to(ROOT):
        parser.error("Choose an absolute directory outside this release")
    for path in (*directory.parents, directory):
        if path.is_symlink():
            parser.error("The instance path must not contain symlinks")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    secret_dir = directory / "secrets"
    if secret_dir.is_symlink():
        parser.error("The secret directory must not be a symlink")
    secret_dir.mkdir(exist_ok=True, mode=0o700)
    secret_dir.chmod(0o700)
    key_file = secret_dir / "storage.key"
    created = False
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        pass  # Startup validates an existing key. Never silently replace it.
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(base64.b64encode(secrets.token_bytes(32)) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        created = True
    print(json.dumps({"dataDir": str(directory / "data"), "secretKeyFile": str(key_file),
                      "keyCreated": created, "scope": "local development only; key content is not printed"}, indent=2))


if __name__ == "__main__":
    main()
