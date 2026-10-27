"""Private local files on POSIX and Windows; never follow reparse points.

Windows uses a protected DACL granting the current user and SYSTEM full control.
The launcher and Store apply it to their own directories before creating files.
"""
import os
from pathlib import Path
import stat


def no_links(path):
    for item in (*reversed(Path(path).parents), Path(path)):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise OSError("Linked/reparse paths are not allowed")


def owned(info):
    # On Windows protected directory ACLs establish ownership, not POSIX mode bits.
    return os.name == "nt" or info.st_uid == os.getuid()


def private_mode(info):
    return os.name == "nt" or not info.st_mode & 0o077


def private_directory(path):
    path = Path(path)
    no_links(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not stat.S_ISDIR(path.stat().st_mode) or not owned(path.stat()):
        raise OSError("Directory ownership is invalid")
    if os.name == "nt":
        _windows_private(path)
    else:
        path.chmod(0o700)


def _windows_private(path):
    import ctypes as C
    from ctypes import wintypes as W
    kernel = C.WinDLL("kernel32", use_last_error=True)
    advapi = C.WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    kernel.LocalFree.argtypes = [C.c_void_p]
    advapi.OpenProcessToken.argtypes = [W.HANDLE, W.DWORD, C.POINTER(W.HANDLE)]
    advapi.GetTokenInformation.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.POINTER(W.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [C.c_void_p, C.POINTER(W.LPWSTR)]
    advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(C.c_void_p), C.POINTER(W.DWORD)]
    advapi.SetFileSecurityW.argtypes = [W.LPCWSTR, W.DWORD, C.c_void_p]
    token, size, text, descriptor = W.HANDLE(), W.DWORD(), W.LPWSTR(), C.c_void_p()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, C.byref(token)):
        raise C.WinError(C.get_last_error())
    try:
        advapi.GetTokenInformation(token, 1, None, 0, C.byref(size))
        buffer = C.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, 1, buffer, size, C.byref(size)):
            raise C.WinError(C.get_last_error())
        sid = C.cast(buffer, C.POINTER(C.c_void_p))[0]
        if not advapi.ConvertSidToStringSidW(sid, C.byref(text)):
            raise C.WinError(C.get_last_error())
        sddl = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;" + text.value + ")"
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, C.byref(descriptor), None):
            raise C.WinError(C.get_last_error())
        if not advapi.SetFileSecurityW(str(path), 0x80000004, descriptor):
            raise C.WinError(C.get_last_error())
    finally:
        if descriptor.value:
            kernel.LocalFree(descriptor)
        if text:
            kernel.LocalFree(C.cast(text, C.c_void_p))
        kernel.CloseHandle(token)


def open_private(path, flags, mode=0o600):
    no_links(Path(path))
    if os.name != "nt":
        return os.open(path, flags | os.O_NOFOLLOW, mode)
    import ctypes as C
    from ctypes import wintypes as W
    import msvcrt
    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE]
    kernel.CreateFileW.restype = W.HANDLE
    kernel.CloseHandle.argtypes = [W.HANDLE]
    class Info(C.Structure):
        _fields_ = [("attributes", W.DWORD), ("creation", W.FILETIME), ("access", W.FILETIME),
                    ("write", W.FILETIME), ("volume", W.DWORD), ("sizeHigh", W.DWORD),
                    ("sizeLow", W.DWORD), ("links", W.DWORD), ("indexHigh", W.DWORD), ("indexLow", W.DWORD)]
    kernel.GetFileInformationByHandle.argtypes = [W.HANDLE, C.POINTER(Info)]
    access = 0x80000000
    if flags & (os.O_WRONLY | os.O_RDWR):
        access |= 0x40000000
    disposition = 1 if flags & os.O_EXCL else (2 if flags & os.O_TRUNC else (4 if flags & os.O_CREAT else 3))
    handle = kernel.CreateFileW(str(path), access, 7, None, disposition, 0x00200080, None)
    if handle == W.HANDLE(-1).value:
        raise C.WinError(C.get_last_error())
    info = Info()
    try:
        if not kernel.GetFileInformationByHandle(handle, C.byref(info)):
            raise C.WinError(C.get_last_error())
        if info.attributes & (0x400 | 0x10) or info.links != 1:
            raise OSError("A private file cannot be a link or directory")
        fd = msvcrt.open_osfhandle(handle, (flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR)) | os.O_BINARY)
        handle = None  # Ownership transferred to the CRT descriptor.
        return fd
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
