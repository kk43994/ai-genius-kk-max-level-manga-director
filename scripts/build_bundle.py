#!/usr/bin/env python3
"""Build a deterministic source run package from one committed tree, without data or legacy engines."""
import argparse
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "asset-lab-customer/"
ROOT_FILES = {"README.md", "requirements.txt", "pyproject.toml", "package.json", "package-lock.json", ".env.example", ".gitignore", "release-manifest.example.json"}
SOURCE_DIRS = {"backend", "frontend", "docs", "examples", "scripts", "tests", "deploy"}
EXTENSIONS = {".py", ".js", ".mjs", ".cjs", ".html", ".css", ".md", ".txt", ".json", ".toml", ".sh", ".yml", ".yaml", ".svg", ".png", ".ico", ".woff2", ".service", ".conf"}
DENIED_PARTS = {"legacy", "__pycache__", "node_modules", "private", "credentials", "secrets", "data", "runtime", "work", "outputs", ".git", ".libtv"}


def git(*args):
    return subprocess.check_output(["git", "-C", str(ROOT), *args])


def include(path):
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or any(p in DENIED_PARTS for p in pure.parts):
        return False
    if path in ROOT_FILES:
        return True
    return (pure.parts[0] in SOURCE_DIRS and (pure.suffix in EXTENSIONS or path.endswith((".service.example", ".conf.example")))
            and not any(part.startswith(".") for part in pure.parts))


def build(commit):
    if Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve() != ROOT:
        raise ValueError("Build must run in the independent customer repository")
    resolved = git("rev-parse", "--verify", commit + "^{commit}").decode().strip()
    entries = []
    for entry in git("ls-tree", "-r", "-z", resolved).split(b"\0"):
        if not entry:
            continue
        metadata, path_bytes = entry.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        path = path_bytes.decode()
        if include(path):
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError(f"Refusing non-regular package entry: {path}")
            entries.append((path, git("cat-file", "blob", blob), mode))
    manifest = {
        "formatVersion": 1, "product": "asset-lab-customer", "sourceCommit": resolved,
        "scope": "integration checkpoint; customerReady=false",
        "files": [{"path": path, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
                  for path, raw, mode in sorted(entries)],
        "excludes": ["legacy engines", "customer data", "local credentials", "Git metadata"],
    }
    entries.append(("BUNDLE-MANIFEST.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(), "100644"))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path, raw, mode in sorted(entries):
            info = zipfile.ZipInfo(PREFIX + path, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100755 if mode == "100755" else 0o100644) << 16
            archive.writestr(info, raw, compresslevel=9)
    content = output.getvalue()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if archive.testzip() is not None:
            raise ValueError("Package CRC check failed")
        for item in manifest["files"]:
            if hashlib.sha256(archive.read(PREFIX + item["path"])).hexdigest() != item["sha256"]:
                raise ValueError("Package hash check failed")
    return content, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--commit", default="HEAD")
    args = parser.parse_args()
    content, manifest = build(args.commit)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    args.output.with_suffix(args.output.suffix + ".sha256").write_text(f"{checksum}  {args.output.name}\n")
    print(json.dumps({"output": str(args.output.resolve()), "sourceCommit": manifest["sourceCommit"],
                      "files": len(manifest["files"]), "sha256": checksum, "verified": True}, indent=2))


if __name__ == "__main__":
    main()
