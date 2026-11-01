"""Detached installer handoff after the old workbench exits. No forced kills."""
import os
from pathlib import Path
import subprocess
import sys
import time

from local_client.updater import verified_file, version_key


def wait_for_exit(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 87
        try:
            return kernel.WaitForSingleObject(handle, 180000) == 0
        finally:
            kernel.CloseHandle(handle)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try: os.kill(pid, 0)
        except ProcessLookupError: return True
        time.sleep(.25)
    return False


def main(arguments):
    if len(arguments) != 6:
        return 2
    pid, filename, checksum, size, version, target = arguments
    try:
        pid = int(pid); row = {'sha256': checksum, 'bytes': int(size)}
        version_key(version)
        path = Path(filename)
        extension = '.exe' if target == 'windows-x64' else '.pkg'
        if pid <= 1 or target not in ('windows-x64', 'macos-arm64') or path.name != checksum + extension:
            return 2
        if not wait_for_exit(pid) or not verified_file(path, row):
            return 3
        if target == 'windows-x64' and sys.platform == 'win32':
            result = subprocess.run([str(path), '/S'], check=False)
            if result.returncode:
                return result.returncode
            # NSIS retains previous version directories and updates shortcuts only
            # after copying the new program. Customer data lives elsewhere.
            current = Path(sys.executable).resolve().parents[1]
            updated = current.parent / version
            python = updated / 'runtime/pythonw.exe'
            launcher = updated / 'server/local_client/launch.py'
            if python.is_file() and launcher.is_file():
                subprocess.Popen([str(python), '-X', 'utf8', str(launcher), '--frontend', str(updated / 'public')])
            return 0
        if target == 'macos-arm64' and sys.platform == 'darwin':
            return subprocess.run(['/usr/bin/open', str(path)], check=False).returncode
        return 2
    except (OSError, ValueError, IndexError):
        return 3
