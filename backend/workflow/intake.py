"""Migrated script extraction; import is deliberately independent of analysis."""
import base64
import binascii
import hashlib
import io
import re
import stat
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree

from .errors import invalid, public_input

MAX_FILE = 8 * 1024 * 1024
MAX_TEXT = 250_000
MAX_UNPACKED = 32 * 1024 * 1024
ANALYSIS = {'configured': False, 'state': 'unavailable', 'status': 'not_configured',
            'method': 'ai', 'localRuleFallback': False,
            'message': '原文已保存，AI 分析尚未开始；不会使用本地规则替代。'}


def decode_script(payload):
    public_input(payload, {'filename', 'contentBase64'})
    name, encoded = payload.get('filename'), payload.get('contentBase64')
    if (not isinstance(name, str) or not name.strip() or len(name) > 240
            or name in ('.', '..') or re.search(r'[\\/:\x00-\x1f\x7f]', name)):
        invalid('文件名无效；请选择不含路径的剧本文件。')
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in ('.txt', '.md', '.docx'):
        invalid('请选择 TXT、Markdown 或 DOCX 剧本。')
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FILE + 2) // 3):
        invalid('剧本为空或超过 8 MiB。')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        invalid('文件上传内容损坏，请重试。')
    if not raw or len(raw) > MAX_FILE:
        invalid('剧本为空或超过 8 MiB。')
    text = extract_script(suffix, raw)
    return {'filename': name, 'sourceRevision': hashlib.sha256(raw).hexdigest(),
            'text': text, 'characters': len(text)}, raw


def extract_script(suffix, raw):
    if suffix == '.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                entries = archive.infolist()
                names = [info.filename for info in entries]
                if len(entries) > 2000 or len(set(names)) != len(names):
                    invalid('DOCX 文件条目异常。')
                if sum(info.file_size for info in entries) > MAX_UNPACKED:
                    invalid('DOCX 解压内容过大，请导出 TXT 后导入。')
                for info in entries:
                    path = PurePosixPath(info.filename)
                    if (path.is_absolute() or '..' in path.parts or '\\' in info.filename
                            or ':' in info.filename or info.flag_bits & 1
                            or stat.S_ISLNK(info.external_attr >> 16)):
                        invalid('DOCX 含不安全的文件条目。')
                    if info.file_size > 1024 * 1024 and info.file_size > max(1, info.compress_size) * 150:
                        invalid('DOCX 压缩比例异常，请导出 TXT 后导入。')
                xml = archive.read('word/document.xml')
                # UTF-16 XML must not hide a DTD/entity declaration from this check.
                scan = xml.replace(b'\x00', b'').upper()
                if b'<!DOCTYPE' in scan or b'<!ENTITY' in scan:
                    invalid('DOCX 包含不支持的 XML 内容。')
                root = ElementTree.fromstring(xml)
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                text = '\n'.join(''.join(t.text or '' for t in p.iter(ns + 't'))
                                 for p in root.iter(ns + 'p'))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, OSError, NotImplementedError):
            invalid('DOCX 无法读取，请重新导出。')
    else:
        text = None
        encodings = ('utf-16',) if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'gb18030')
        for encoding in encodings:
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            invalid('文字编码无法读取，请保存为 UTF-8 后导入。')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', text):
        invalid('文件含不可读的控制字符，请导出为纯文本。')
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text or len(text) > MAX_TEXT:
        invalid('未读取到正文或正文超过 25 万字。')
    return text
