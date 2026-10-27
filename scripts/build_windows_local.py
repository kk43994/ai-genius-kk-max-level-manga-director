#!/usr/bin/env python3
"""Build a data-free Windows x64 local authorization preview with its own Python."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

from build_customer import build

ROOT = Path(__file__).resolve().parents[1]
PYTHON_VERSION = "3.14.10"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def get_runtime(cache):
    url = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/windows-{PYTHON_VERSION}.json"
    with urllib.request.urlopen(url, timeout=30) as response:
        metadata = json.load(response)
    choices = [v for v in metadata["versions"] if v["id"] == "pythonembed-3.14-64"]
    if len(choices) != 1:
        raise ValueError("Official embed runtime not uniquely identified")
    chosen = choices[0]
    if chosen["url"] != f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embeddable-amd64.zip":
        raise ValueError("Unexpected Python download location")
    archive = cache / f"python-{PYTHON_VERSION}-embed-amd64.zip"
    if not archive.exists() or digest(archive) != chosen["hash"]["sha256"]:
        temporary = archive.with_suffix(".download")
        with urllib.request.urlopen(chosen["url"], timeout=30) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(temporary) != chosen["hash"]["sha256"]:
            temporary.unlink()
            raise ValueError("Official Python runtime hash mismatch")
        temporary.replace(archive)
    return archive, {"metadataUrl": url, "downloadUrl": chosen["url"], "sha256": digest(archive)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    cache = ROOT / "work/windows-wheels"
    cache.mkdir(parents=True, exist_ok=True)
    runtime_zip, provenance = get_runtime(cache)
    wheels = sorted(cache.glob("*.whl"))
    if not wheels:
        raise ValueError("Download pinned win_amd64 wheels into work/windows-wheels first")
    build(ROOT / ".build", "/asset-lab/", "/asset-lab/api/v1")
    stage = ROOT / "work/windows-package/AssetLab"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copytree(ROOT / ".build/public", stage / "public")
    shutil.copytree(ROOT / ".build/server", stage / "server")
    client = stage / "server/local_client"
    client.mkdir()
    for name in ("__init__.py", "launch.py"):
        shutil.copyfile(ROOT / "local_client" / name, client / name)
    runtime = stage / "runtime"
    runtime.mkdir()
    with zipfile.ZipFile(runtime_zip) as archive:
        for name in archive.namelist():
            if "/" in name or "\\" in name or ":" in name or name.startswith("."):
                raise ValueError("Unexpected Python runtime path")
        archive.extractall(runtime)
    # Embeddable Python ignores PATH, registry installations and user site packages.
    (runtime / "python314._pth").write_text("python314.zip\n.\n../server\nLib/site-packages\nimport site\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--no-compile", "--only-binary=:all:",
                    "--platform", "win_amd64", "--python-version", "3.14", "--implementation", "cp", "--abi", "cp314",
                    "--find-links", str(cache), "--target", str(runtime / "Lib/site-packages"),
                    "-r", str(ROOT / "requirements.txt")], check=True)
    command = '@echo off\r\nchcp 65001 >nul\r\nstart "" "%~dp0runtime\\pythonw.exe" "%~dp0server\\local_client\\launch.py" --frontend "%~dp0public"\r\n'
    (stage / "启动资产实验室.cmd").write_bytes(command.encode("utf-8"))
    (stage / "使用说明.txt").write_text(
        "资产实验室 · Windows 本地连接预览 0.2.0-local.1\n\n"
        "1. 将整个 ZIP 解压到一个文件夹。不要在压缩包预览中运行。\n"
        "2. 双击“启动资产实验室.cmd”，浏览器会打开本机工作台。无需安装 Python、Codex 或 CLI。\n"
        "3. 点击“授权 LibTV”，在 LibTV 官方页面登录并确认账号读取权限。\n"
        "4. 工作台自动核验账号并查询个人/团队空间；选择空间后点击“应用到新任务”。\n"
        "5. 再次启动会恢复本机已保存的工作区和授权。令牌失效时使用“重新授权”。\n\n"
        "数据保存在 %LOCALAPPDATA%\\AssetLab；程序文件夹与数据分开。请保留其中的 secrets 文件夹，否则无法解密已保存的授权。\n"
        "使用页面底部“退出本地工作台”可停止本地服务。再次双击启动即可继续。\n\n"
        "本版仅开放 LibTV 账号读取；生成、付费调用和自动安装更新暂未开放。\n"
        "开发机已完成真实官方只读授权、身份/空间回读和重启保留连接；Windows 实机验证仍待完成。\n",
        encoding="utf-8-sig")
    provenance.update(wheels=[{"file": w.name, "sha256": digest(w)} for w in wheels],
                      platform="windows-amd64", python=PYTHON_VERSION, version="0.2.0-local.1",
                      liveUserCredentialsIncluded=False, windowsRuntimeExecuted=False,
                      sourceCommit=subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip())
    (stage / "build-provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    files = {p.relative_to(stage).as_posix(): digest(p) for p in sorted(stage.rglob("*")) if p.is_file()}
    (stage / "files-sha256.json").write_text(json.dumps(files, ensure_ascii=False, indent=2), encoding="utf-8")
    target = args.output / "AssetLab-Windows-x64-0.2.0-local.1.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_symlink():
                raise ValueError("Package cannot contain symlinks")
            if path.is_file():
                archive.write(path, (Path("AssetLab") / path.relative_to(stage)).as_posix())
    target.with_suffix(".zip.sha256").write_text(digest(target) + "  " + target.name + "\n")
    print(json.dumps({"package": str(target), "bytes": target.stat().st_size, "sha256": digest(target),
                      "credentialFree": True, "windowsRuntimeExecuted": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
