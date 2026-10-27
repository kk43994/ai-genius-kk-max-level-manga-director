"""Durable script intake. Analysis is a separate, not-yet-configured provider.

Import never calls an LLM, changes the existing production manifest, or submits
images. A future analyzer must consume the saved source revision and return the
structured contract in script-analysis-contract.json.
"""
import base64
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

from production_actions import ActionError, atomic_json

MAX_FILE = 8 * 1024 * 1024
MAX_TEXT = 250_000

def capabilities():
    return {'configured': False, 'status': 'not_configured', 'model': None,
            'message': '分析模型待接入', 'contractVersion': 1}

def extract_script(filename, raw):
    suffix = Path(filename).suffix.lower()
    if suffix not in ('.docx', '.txt', '.md'):
        raise ActionError('请选择 DOCX、TXT 或 Markdown 剧本。')
    if not raw or len(raw) > MAX_FILE:
        raise ActionError('剧本文件为空或超过 8 MB。')
    if suffix == '.docx':
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if sum(f.file_size for f in archive.infolist()) > 32 * 1024 * 1024:
                    raise ActionError('DOCX 解压内容过大，请导出为 TXT 后导入。')
                xml = archive.read('word/document.xml')
                if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:
                    raise ActionError('DOCX 包含不支持的 XML 内容。')
                root = ElementTree.fromstring(xml)
                ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
                text = '\n'.join(''.join(t.text or '' for t in p.iter(ns+'t')) for p in root.iter(ns+'p'))
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, RuntimeError, OSError):
            raise ActionError('DOCX 无法读取，请重新导出文件。') from None
    else:
        text = None
        encodings = ('utf-16',) if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ('utf-8-sig', 'gb18030')
        for encoding in encodings:
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                pass
        if text is None or '\x00' in text:
            raise ActionError('文字编码无法读取，请保存为 UTF-8 后导入。')
    text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
    if not text:
        raise ActionError('没有读取到正文；请导入含文字的剧本。')
    if len(text) > MAX_TEXT:
        raise ActionError('剧本超过 25 万字，请按集拆分后导入。')
    return text

def script_folder(root, script_id):
    if not isinstance(script_id, str) or not re.fullmatch(r'script-[0-9a-f]{24}', script_id):
        raise ActionError('剧本编号无效。', 404)
    return root / 'scripts' / script_id

def list_scripts(root):
    records = []
    for path in (root / 'scripts').glob('script-*/record.json'):
        record = json.loads(path.read_text())
        records.append(record)
    return {'scripts': sorted(records, key=lambda r: r['importedAt'], reverse=True), 'analysis': capabilities()}

def read_script(root, script_id):
    folder = script_folder(root, script_id)
    if not (folder / 'record.json').is_file():
        raise ActionError('未找到这个剧本。', 404)
    record = json.loads((folder / 'record.json').read_text())
    return {**record, 'text': (folder / 'text.txt').read_text(), 'analysis': capabilities()}

def import_script(root, payload, lock):
    name, encoded = payload.get('filename'), payload.get('contentBase64')
    if not isinstance(name, str) or not name.strip() or len(name) > 240:
        raise ActionError('文件名无效。')
    name = name.replace('\\', '/').split('/')[-1]
    if not isinstance(encoded, str) or len(encoded) > MAX_FILE * 4 // 3 + 4:
        raise ActionError('文件内容为空或超过 8 MB。')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise ActionError('文件上传内容损坏，请重试。') from None
    text = extract_script(name, raw)
    digest = hashlib.sha256(raw).hexdigest()
    script_id = 'script-' + digest[:24]
    folder = script_folder(root, script_id)
    with lock:
        if (folder / 'record.json').exists():
            return {'ok': True, 'duplicate': True, 'script': read_script(root, script_id)}
        folder.mkdir(parents=True, exist_ok=True)
        source_name = 'source' + Path(name).suffix.lower()
        (folder / source_name).write_bytes(raw)
        (folder / 'text.txt').write_text(text, encoding='utf-8')
        record = {'id': script_id, 'filename': name, 'sourceFile': source_name,
                  'sourceRevision': digest, 'characters': len(text), 'version': 1,
                  'importedAt': datetime.now(timezone.utc).isoformat(),
                  'analysisStatus': 'not_started', 'result': None}
        atomic_json(folder / 'record.json', record)
    return {'ok': True, 'duplicate': False, 'script': {**record, 'text': text, 'analysis': capabilities()}}

def start_analysis(root, payload):
    record = read_script(root, payload.get('scriptId'))
    if record['sourceRevision'] != payload.get('sourceRevision'):
        raise ActionError('剧本版本已变化，请重新读取。', 409)
    # Deliberately no fallback to regex, canned project data, or this chat's AI.
    raise ActionError('分析模型尚未接入；剧本已保存，暂未开始分析。', 503)
