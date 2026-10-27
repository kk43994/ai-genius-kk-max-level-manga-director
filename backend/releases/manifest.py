"""Strict v1 release-manifest validation. Kept wire-compatible with deploy/release.py.

Both validators are covered by common rejection and round-trip fixtures.
"""
import datetime as dt
import hashlib
import json
import re
from pathlib import PurePosixPath
from urllib.parse import urljoin, urlsplit

PRODUCT = 'asset-lab-customer'
VERSION_RE = re.compile(r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$')
DENIED_PART = re.compile(r'(^\.|^(data|uploads|credentials?|secrets?|sessions?|tokens?|cookies?|node_modules|backups|runtime|logs)([.-]|$)|\.(db|sqlite|sqlite3|pem|key|p12|pfx|log)$|(^|[-_.])(credential|secret|cookie|token|oauth)([-_.]|$))', re.I)
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\b(?:sk-proj-|sk-ant-api)[A-Za-z0-9_-]{16,}|\bgh[pousr]_[A-Za-z0-9]{30,}|\bAKIA[A-Z0-9]{16}\b')
MARKER = '.asset-lab-release-root'

def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def digest_file(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()

def fail(message):
    raise ValueError(message)

def version(value):
    match = VERSION_RE.fullmatch(value) if isinstance(value, str) and len(value) <= 128 else None
    if not match or any(re.fullmatch(r'0[0-9]+', x) for x in (match[4] or '').split('.')):
        fail('Invalid semantic version')
    return tuple(int(match[i]) for i in (1, 2, 3)), (match[4] or '').split('.') if match[4] else []

def compare(a, b):
    ac, ap = version(a); bc, bp = version(b)
    if ac != bc:
        return 1 if ac > bc else -1
    if not ap or not bp:
        return 0 if not ap and not bp else (1 if not ap else -1)
    for a, b in zip(ap, bp):
        if a == b:
            continue
        an, bn = a.isdigit(), b.isdigit()
        if an != bn:
            return -1 if an else 1
        return 1 if (int(a) > int(b) if an else a > b) else -1
    return (len(ap) > len(bp)) - (len(ap) < len(bp))

def shape(obj, keys, label):
    if not isinstance(obj, dict) or set(obj) != set(keys.split()):
        fail('Invalid ' + label + ' fields')

def manifest_valid(m, origin, base_path):
    shape(m, 'schemaVersion product version buildId channel publishedAt apiVersion dataSchemaVersion minCompatibleClient releaseNotes reloadRequired entryUrl integrity', 'manifest')
    if type(m['schemaVersion']) is not int or m['schemaVersion'] != 1 or m['product'] != PRODUCT or m['channel'] not in ('stable', 'preview'):
        fail('Unsupported manifest')
    _, pre = version(m['version'])
    if m['channel'] == 'stable' and pre:
        fail('Stable channel cannot contain a prerelease')
    if not isinstance(m['buildId'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', m['buildId']):
        fail('Invalid build identifier')
    stamp = m['publishedAt']
    if not isinstance(stamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', stamp):
        fail('Invalid release date')
    dt.datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ')
    notes = m['releaseNotes']
    if not isinstance(notes, list) or len(notes) > 30 or any(not isinstance(x, str) or not 0 < len(x) <= 2000 for x in notes):
        fail('Invalid release notes')
    if any(type(m[k]) is not int or not 1 <= m[k] <= 9007199254740991 for k in ('apiVersion', 'dataSchemaVersion')) or type(m['reloadRequired']) is not bool:
        fail('Invalid compatibility fields')
    version(m['minCompatibleClient'])
    if compare(m['minCompatibleClient'], m['version']) > 0:
        fail('Release does not support its own client')
    shape(m['integrity'], 'algorithm value', 'integrity')
    if m['integrity']['algorithm'] != 'sha256' or not isinstance(m['integrity']['value'], str) or not re.fullmatch(r'[a-f0-9]{64}', m['integrity']['value']):
        fail('Invalid payload digest')
    entry = m['entryUrl']
    if not isinstance(entry, str) or len(entry) > 2048 or re.search(r'[\\\s]', entry) or not re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)*', base_path):
        fail('Invalid entry URL')
    u, expected = urlsplit(urljoin(origin + '/', entry)), urlsplit(origin)
    if (u.scheme, u.netloc) != (expected.scheme, expected.netloc) or u.username or u.password or u.query or u.fragment or not u.path.startswith(base_path) or re.search(r'%2f|%5c|%2e', u.path, re.I) or '..' in PurePosixPath(u.path).parts:
        fail('Untrusted entry URL')
    if u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('localhost', '127.0.0.1', '::1')):
        fail('HTTPS required outside loopback')
    if SECRET.search(encoded(m)):
        fail('Credential pattern in release metadata')
    return m

def release_id(m):
    return m['version'] + '--' + m['buildId']
