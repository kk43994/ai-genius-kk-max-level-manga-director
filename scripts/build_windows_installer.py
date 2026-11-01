#!/usr/bin/env python3
"""Compile the verified Windows payload into a per-user desktop installer."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_client import APP_VERSION, APP_BUNDLE_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output = args.output.resolve()
    stage = ROOT / "work/windows-package/AssetLab"
    inventory = json.loads((stage / "files-sha256.json").read_text())
    actual = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()}
    if actual != set(inventory) | {"files-sha256.json"}:
        raise ValueError("Unlisted files in Windows payload")
    for path, digest in inventory.items():
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise ValueError("Invalid payload inventory path")
        file = stage / path
        if file.is_symlink() or hashlib.sha256(file.read_bytes()).hexdigest() != digest:
            raise ValueError("Payload verification failed: " + path)
    if any(p.name in {"storage.key", "state.sqlite3", ".env"} or p.is_symlink() for p in stage.rglob("*")):
        raise ValueError("Private runtime state must not be packaged")
    provenance = json.loads((stage / "build-provenance.json").read_text())
    if provenance["version"] != APP_VERSION:
        raise ValueError("Rebuild Windows payload before installer")
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.output / f"AssetLab-Setup-{APP_VERSION}-x64.exe"
    subprocess.run(["makensis", "-V2", f"-DSTAGEDIR={stage}", f"-DOUTFILE={target}",
                    f"-DAPPVERSION={APP_VERSION}", f"-DBUNDLEVERSION={APP_BUNDLE_VERSION}",
                    str(ROOT / "local_client/installer.nsi")], check=True)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".exe.sha256").write_text(digest + "  " + target.name + "\n")
    print(json.dumps({"installer": str(target), "version": APP_VERSION, "bytes": target.stat().st_size,
                      "sha256": digest, "signed": False, "windowsInstallExecuted": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
