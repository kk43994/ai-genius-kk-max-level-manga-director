"""Double-click entry for a self-contained Windows package; no CLI login needed."""
import argparse
import atexit
import base64
import hashlib
import http.client
import json
import logging
import os
from pathlib import Path
import secrets
import signal
import sys
import threading
import webbrowser

# Embeddable Python explicitly includes server/ in its ._pth; source runs need it too.
SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
from backend.storage.platform_fs import private_directory, open_private, no_links
from local_client import APP_VERSION


def default_instance():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base or not Path(base).is_absolute():
            raise ValueError("无法确定 Windows 本地应用目录")
        return Path(base) / "AssetLab"
    return Path.home() / "Library/Application Support/AssetLab"


def provision(instance):
    if not instance.is_absolute() or instance.resolve().is_relative_to(SERVER):
        raise ValueError("工作区必须独立于程序目录")
    no_links(instance)
    private_directory(instance)
    private_directory(instance / "secrets")
    private_directory(instance / "logs")
    key = instance / "secrets/storage.key"
    if (instance / "data/state.sqlite3").exists() and not key.exists():
        raise ValueError("已有工作区的存储密钥缺失，已停止启动以保护原资料")
    try:
        fd = open_private(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, "wb") as handle:
            handle.write(base64.b64encode(secrets.token_bytes(32)) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
    return key


def local_json(port, path):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            return None
        return json.loads(response.read(16384)).get("data")
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def hold_windows_process_lock():
    """Keep the installer from replacing a running customer's application files."""
    if os.name != "nt":
        return
    import ctypes as C
    from ctypes import wintypes as W
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
    kernel.CreateMutexW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    handle = kernel.CreateMutexW(None, False, "Local\\AssetLab.Workbench")
    if not handle:
        raise C.WinError(C.get_last_error())
    if C.get_last_error() == 183:
        kernel.CloseHandle(handle)
        raise RuntimeError("本地工作台已在启动或运行")
    atexit.register(kernel.CloseHandle, handle)


def run(instance, *, port=18874, open_browser=True, frontend=None, version=APP_VERSION):
    from backend.app import Config, CustomerHTTPServer, Response, create_app
    from backend.storage import SCHEMA_VERSION
    key = provision(instance)
    origin, base = f"http://127.0.0.1:{port}", "/asset-lab/"
    identity = hashlib.sha256(str(instance.resolve()).encode()).hexdigest()
    existing = local_json(port, base + "api/v1/local-runtime")
    if existing and existing.get("instanceId") == identity and existing.get("mode") == "local-client":
        if open_browser:
            webbrowser.open(origin + base)
        return 0
    hold_windows_process_lock()
    config = Config(instance / "data", port=port, public_base_path=base,
                    secret_key_file=key, local_client=True,
                    frontend_dir=frontend or SERVER / "frontend")
    app = create_app(config)
    app.build_info.update(version=version, channel="preview", dataSchemaVersion=SCHEMA_VERSION)
    runtime = {"mode": "local-client", "instanceId": identity, "version": version,
               "accountAuthorization": True, "scopes": ["libtv:account:read"],
               "automaticUpdates": False}
    app.router.add("GET", "/api/v1/local-runtime", lambda ctx, params: Response(body=runtime), public=True)
    server = CustomerHTTPServer(app)
    # Existing web version UI expects release metadata; a local auth preview has
    # no live update feed. It must never present a page refresh as an installation.
    def stop(ctx, params):
        threading.Thread(target=server.shutdown, daemon=True).start()
        return Response(body={"stopping": True})
    app.router.add("POST", "/api/v1/local-runtime/stop", stop)
    def shutdown(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, shutdown)
    if open_browser:
        timer = threading.Timer(0.5, lambda: webbrowser.open(origin + base))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path)
    parser.add_argument("--port", type=int, default=18874)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--frontend", type=Path)
    args = parser.parse_args()
    instance = (args.instance or default_instance()).absolute()
    try:
        private_directory(instance / "logs")
        logging.basicConfig(filename=instance / "logs/launcher.log", level=logging.ERROR,
                            format="%(asctime)s %(levelname)s %(message)s")
        return run(instance, port=args.port, open_browser=not args.no_browser, frontend=args.frontend)
    except Exception as error:
        # Never log URL queries, provider responses, tokens or credential contents.
        logging.error("launcher_failed type=%s", type(error).__name__)
        message = "资产实验室启动失败。请检查本地端口是否被占用，或将 logs/launcher.log 提供给支持人员。已有项目与账号数据未被替换。"
        if os.name == "nt" and not args.no_browser:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "资产实验室", 0x10)
        elif sys.platform == "darwin" and getattr(sys, "frozen", False) and not args.no_browser:
            import subprocess
            native = Path(sys.executable).parents[2] / "MacOS/AssetLab"
            subprocess.run([str(native), "--show-error"], check=False)
        else:
            print(message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
