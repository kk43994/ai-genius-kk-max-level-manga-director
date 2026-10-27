#!/usr/bin/env python3
"""Dependency-free build/install/rollback CLI. Python 3.11+, macOS or Linux.

SHA-256 protects integrity; the SSH transport and operator-provided digest are
the trust boundary. A downloaded checksum is not a publisher signature.
"""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import urljoin, urlsplit, unquote
import uuid

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

def safe_path(name):
    p = PurePosixPath(name)
    if not isinstance(name, str) or not name or p.is_absolute() or '\\' in name or any(x in ('..', '.') for x in p.parts) or str(p) != name or re.search(r'[\x00-\x1f\x7f]', name):
        fail('Unsafe artifact path')
    for index, part in enumerate(p.parts):
        # backend/sessions and auth/tokens.py are CODE modules in the customer
        # contract. Keep actual .json credential files and data directories out.
        code_tree = len(p.parts) >= 3 and p.parts[:2] == ('server', 'backend')
        source_module = code_tree and not part.startswith('.') and (part.endswith('.py') or (index == 2 and part == 'sessions'))
        if DENIED_PART.search(part) and not source_module:
            fail('Sensitive/runtime path forbidden in artifact: ' + name)
    if p.parts[0] not in ('public', 'server', 'build-evidence.json', 'files.json', 'release.json'):
        fail('Unexpected artifact root')
    return p

def scan_file(path):
    # Credential detection is defense in depth. The explicit source allowlist is
    # mandatory and code review remains necessary for application-specific data.
    if path.stat().st_size > 256 * 1024 * 1024:
        fail('Oversized artifact file')
    with path.open('rb') as f:
        tail = b''
        while block := f.read(1024 * 1024):
            if SECRET.search(tail + block):
                fail('Credential pattern in artifact file: ' + path.name)
            tail = block[-256:]

def inventory(directory):
    result = []
    for p in sorted(directory.rglob('*')):
        if p.is_symlink() or not (p.is_dir() or p.is_file()):
            fail('Symlinks and special files are forbidden')
        rel = p.relative_to(directory).as_posix()
        safe_path(rel)
        if p.is_file() and rel not in ('release.json', 'files.json'):
            scan_file(p)
            result.append({'path': rel, 'size': p.stat().st_size, 'sha256': digest_file(p)})
    return result

def read_json(path, max_size=4 * 1024 * 1024):
    if path.stat().st_size > max_size:
        fail('Oversized JSON file')
    return json.loads(path.read_text())

def verify_directory(directory, origin, base_path, channel=None):
    m = manifest_valid(read_json(directory / 'release.json', 131072), origin, base_path)
    if channel and m['channel'] != channel:
        fail('Artifact channel mismatch')
    if sha((directory / 'files.json').read_bytes()) != m['integrity']['value']:
        fail('Inventory digest mismatch')
    if read_json(directory / 'files.json') != inventory(directory):
        fail('Artifact file inventory mismatch')
    if not (directory / 'public' / 'index.html').is_file():
        fail('Artifact needs public/index.html')
    build = read_json(directory / 'build-evidence.json')
    if build.get('buildExitCode') != 0 or build.get('testExitCode') != 0:
        fail('Build/test attestation missing')
    return m

def run_command(command, cwd, env=None):
    if not isinstance(command, list) or not command or any(not isinstance(x, str) or '\x00' in x for x in command):
        fail('Commands must be nonempty JSON argument arrays, never shell strings')
    subprocess.run(command, cwd=cwd, env=env, check=True, timeout=600)

def build_bundle(spec_path, output):
    spec = read_json(spec_path)
    shape(spec, 'schemaVersion sourceDir include buildCommand testCommand release origin basePath', 'build spec')
    if spec['schemaVersion'] != 1:
        fail('Unsupported build spec')
    source = (spec_path.parent / spec['sourceDir']).resolve()
    output = output.resolve()
    if output.exists():
        fail('Bundle output already exists; use a new name')
    includes = spec['include']
    if not isinstance(includes, dict) or 'public' not in includes or set(includes) - {'public', 'server'}:
        fail('Only explicit public/server input directories are accepted')
    m = json.loads(json.dumps(spec['release'])); m['integrity'] = {'algorithm': 'sha256', 'value': '0' * 64}
    manifest_valid(m, spec['origin'], spec['basePath'])
    run_command(spec['buildCommand'], source)
    run_command(spec['testCommand'], source)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='asset-lab-build-') as temp:
        stage = Path(temp)
        for target, relative in includes.items():
            src = source / relative
            if not isinstance(relative, str) or Path(relative).is_absolute() or not src.is_dir() or not src.resolve().is_relative_to(source):
                fail('Include source must be a directory within sourceDir')
            for p in [src, *src.rglob('*')]:
                if p.is_symlink() or not (p.is_file() or p.is_dir()):
                    fail('Input symlinks and special files are forbidden')
                safe_path((Path(target) / p.relative_to(src)).as_posix())
                if p.is_file():
                    scan_file(p)
            shutil.copytree(src, stage / target)
        info = {key: m[key] for key in ('schemaVersion', 'product', 'version', 'buildId', 'channel', 'apiVersion', 'dataSchemaVersion')}
        # The app imports this at page/module load, NEVER fetches the live file to
        # infer which version an already-open tab is running.
        html_path = stage / 'public' / 'index.html'
        if not html_path.exists() and (stage / 'public' / 'asset-lab.html').exists():
            shutil.copyfile(stage / 'public' / 'asset-lab.html', html_path)
        html = html_path.read_text()
        if '<base' in html.lower() or 'id="asset-lab-build"' in html:
            fail('HTML already has a base/build stamp; build from fresh output')
        # Version-addressed assets remain reachable after an atomic switch. The
        # SHA-256 inventory covers every byte; unversioned HTML is always no-store.
        base = spec['basePath'] + 'releases/' + release_id(m) + '/'
        stamp = '<base href="' + base + '"><script type="application/json" id="asset-lab-build">' + json.dumps(info).replace('<', '\\u003c') + '</script>'
        html = re.sub(r'<head(\s[^>]*)?>', lambda match: match[0] + stamp, html, count=1, flags=re.I)
        if 'id="asset-lab-build"' not in html:
            fail('public/index.html needs a head element')
        html_path.write_text(html)
        (stage / 'public' / 'build-info.mjs').write_text('export default Object.freeze(' + json.dumps(info, ensure_ascii=False) + ');\n')
        (stage / 'build-evidence.json').write_bytes(encoded({'schemaVersion': 1, 'builtAt': now(), 'buildExitCode': 0, 'testExitCode': 0}))
        (stage / 'files.json').write_bytes(encoded(inventory(stage)))
        m['integrity']['value'] = digest_file(stage / 'files.json')
        (stage / 'release.json').write_bytes(encoded(m))
        verify_directory(stage, spec['origin'], spec['basePath'])
        temp_archive = output.with_name(output.name + '.tmp-' + uuid.uuid4().hex)
        try:
            with tarfile.open(temp_archive, 'w:gz', format=tarfile.PAX_FORMAT) as archive:
                for path in sorted(stage.rglob('*')):
                    archive.add(path, arcname=path.relative_to(stage).as_posix(), recursive=False)
            os.replace(temp_archive, output)
        finally:
            temp_archive.unlink(missing_ok=True)
    checksum = digest_file(output)
    output.with_name(output.name + '.sha256').write_text(checksum + '  ' + output.name + '\n')
    return {'bundle': str(output), 'sha256': checksum, 'releaseId': release_id(m)}

def extract_bundle(bundle, expected, stage):
    if not re.fullmatch(r'[a-f0-9]{64}', expected) or digest_file(bundle) != expected:
        fail('Bundle SHA-256 mismatch')
    if bundle.stat().st_size > 512 * 1024 * 1024:
        fail('Bundle too large')
    seen, total = set(), 0
    with tarfile.open(bundle, 'r:gz') as archive:
        for member in archive:
            p = safe_path(member.name)
            if member.name in seen or len(seen) >= 20000:
                fail('Duplicate or excessive archive entries')
            seen.add(member.name)
            if not (member.isfile() or member.isdir()):
                fail('Archive links and special files are forbidden')
            total += member.size
            if total > 1024 * 1024 * 1024 or member.size > 256 * 1024 * 1024:
                fail('Expanded artifact too large')
            dest = stage / p
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as src, dest.open('xb') as out:
                    shutil.copyfileobj(src, out)

def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)

def atomic_json(path, value):
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with temp.open('xb') as f:
        f.write(encoded(value)); f.flush(); os.fsync(f.fileno())
    os.replace(temp, path); sync_dir(path.parent)

def atomic_link(path, target):
    if path.exists() and not path.is_symlink():
        fail('Refusing to replace a non-symlink pointer')
    if target is None:
        path.unlink(missing_ok=True); sync_dir(path.parent); return
    temp = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    os.symlink(os.path.relpath(target, path.parent), temp)
    os.replace(temp, path); sync_dir(path.parent)

def pointer(root, channel, name):
    root = root.resolve()
    p = root / 'channels' / channel / name
    if not p.is_symlink():
        if p.exists(): fail('Invalid release pointer')
        return None
    target = p.resolve(strict=True)
    if target.parent != root / 'releases' or not target.is_dir():
        fail('Pointer escapes the release namespace')
    return target

def initialize(root, data):
    if root == data or root.is_relative_to(data) or data.is_relative_to(root) or str(root) in ('/', '/srv', '/opt', '/var'):
        fail('Release root and persistent data must be separate dedicated directories')
    root.mkdir(parents=True, exist_ok=True)
    marker = root / MARKER
    if not marker.exists():
        if any(root.iterdir()): fail('Refusing to initialize a nonempty unmarked directory')
        with marker.open('x') as f: f.write(PRODUCT + '\n')
    if marker.read_text() != PRODUCT + '\n':
        fail('Wrong release namespace marker')
    for d in ('releases', 'staging', 'channels/stable', 'channels/preview', 'audit'):
        (root / d).mkdir(parents=True, exist_ok=True)
    # Existing application data is neither copied, migrated, deleted nor chmodded.
    if not data.exists(): data.mkdir(parents=True, mode=0o700)

@contextlib.contextmanager
def release_lock(root):
    with (root / '.release.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: fail('Another release operation owns the lock')
        yield

def hook(config, name, candidate, data, channel):
    if name not in config: return
    env = dict(os.environ, ASSET_LAB_RELEASE_DIR=str(candidate or ''), ASSET_LAB_DATA_DIR=str(data), ASSET_LAB_CHANNEL=channel)
    run_command(config[name], candidate or data, env)

def require_backend_hooks(candidate, config):
    if (candidate / 'server').exists() and not all(k in config for k in ('quiescenceCommand', 'preflightCommand', 'activateCommand', 'deactivateCommand', 'probeCommand')):
        fail('Backend release requires quiescence, preflight, activate, deactivate and probe hooks')

def audit(root, value):
    atomic_json(root / 'audit' / (now().replace(':', '').replace('-', '') + '-' + uuid.uuid4().hex + '.json'), value)

def restore(root, data, channel, transaction, config):
    folder = root / 'channels' / channel
    old = root / 'releases' / transaction['old'] if transaction['old'] else None
    prev = root / 'releases' / transaction['oldPrevious'] if transaction['oldPrevious'] else None
    if old: require_backend_hooks(old, config)
    atomic_link(folder / 'current', old)
    if old:
        hook(config, 'activateCommand', old, data, channel)
        hook(config, 'probeCommand', old, data, channel)
    else:
        hook(config, 'deactivateCommand', None, data, channel)
    atomic_link(folder / 'previous', prev)

def activate(root, data, channel, candidate, config, operation):
    folder = root / 'channels' / channel
    pending = folder / 'pending.json'
    if pending.exists(): fail('Unfinished release transaction; inspect status and run recover before proceeding')
    old = pointer(root, channel, 'current'); previous = pointer(root, channel, 'previous')
    if old == candidate:
        return {'status': 'unchanged', 'current': candidate.name, 'channel': channel}
    require_backend_hooks(candidate, config)
    if old:
        require_backend_hooks(old, config)
        old_schema = read_json(old / 'release.json')['dataSchemaVersion']
        new_schema = read_json(candidate / 'release.json')['dataSchemaVersion']
        if old_schema != new_schema:
            fail('Data schema change needs a separately reviewed migration; automatic code switch refused')
    # Quiescence must check the actual worker/job store before any backend restart.
    hook(config, 'quiescenceCommand', old or candidate, data, channel)
    hook(config, 'preflightCommand', candidate, data, channel)
    transaction = {'operation': operation, 'channel': channel, 'old': old.name if old else None, 'new': candidate.name, 'oldPrevious': previous.name if previous else None, 'startedAt': now()}
    atomic_json(pending, transaction)
    try:
        atomic_link(folder / 'current', candidate)
        hook(config, 'activateCommand', candidate, data, channel)
        hook(config, 'probeCommand', candidate, data, channel)
        atomic_link(folder / 'previous', old)
        audit(root, dict(transaction, status='succeeded', completedAt=now()))
    except BaseException:
        try:
            restore(root, data, channel, transaction, config)
            audit(root, dict(transaction, status='reverted', completedAt=now()))
            pending.unlink(); sync_dir(folder)
        except BaseException:
            # Leave the durable journal and never claim a healthy rollback.
            audit(root, dict(transaction, status='recovery_required', completedAt=now()))
        raise
    pending.unlink(); sync_dir(folder)
    return {'status': 'succeeded', 'channel': channel, 'current': candidate.name, 'previous': old.name if old else None}

def frozen(directory):
    for path in directory.rglob('*'):
        path.chmod(0o555 if path.is_dir() else 0o444)
        if path.is_file():
            with path.open('rb') as f: os.fsync(f.fileno())
    directory.chmod(0o555)
    for child in sorted((p for p in directory.rglob('*') if p.is_dir()), reverse=True):
        sync_dir(child)
    sync_dir(directory)

def install(args):
    root, data = Path(args.root).resolve(), Path(args.data_root).resolve()
    if args.channel == 'stable' and not args.allow_stable:
        fail('Stable promotion requires explicit --allow-stable after integrated acceptance')
    config = read_json(Path(args.hooks)) if args.hooks else {}
    initialize(root, data)
    with release_lock(root):
        stage = root / 'staging' / uuid.uuid4().hex
        stage.mkdir()
        try:
            extract_bundle(Path(args.bundle), args.sha256, stage)
            m = verify_directory(stage, args.origin, args.base_path, args.channel)
            destination = root / 'releases' / release_id(m)
            if destination.exists():
                existing = verify_directory(destination, args.origin, args.base_path, args.channel)
                if existing != m: fail('Immutable release identifier already exists with different content')
            else:
                os.replace(stage, destination)
            frozen(destination); sync_dir(destination.parent)
            old = pointer(root, args.channel, 'current')
            if old: verify_directory(old, args.origin, args.base_path, args.channel)
            return activate(root, data, args.channel, destination, config, 'install')
        finally:
            if stage.exists(): shutil.rmtree(stage)

def rollback(args):
    root, data = Path(args.root).resolve(), Path(args.data_root).resolve()
    config = read_json(Path(args.hooks)) if args.hooks else {}
    initialize(root, data)
    with release_lock(root):
        candidate = pointer(root, args.channel, 'previous')
        if not candidate: fail('No previous release to roll back to')
        verify_directory(candidate, args.origin, args.base_path, args.channel)
        old = pointer(root, args.channel, 'current')
        if old: verify_directory(old, args.origin, args.base_path, args.channel)
        return activate(root, data, args.channel, candidate, config, 'rollback')

def recover(args):
    root, data = Path(args.root).resolve(), Path(args.data_root).resolve()
    config = read_json(Path(args.hooks)) if args.hooks else {}
    initialize(root, data)
    with release_lock(root):
        pending = root / 'channels' / args.channel / 'pending.json'
        transaction = read_json(pending)
        for key in ('old', 'oldPrevious'):
            if transaction[key]:
                if '/' in transaction[key] or transaction[key] in ('.', '..'): fail('Invalid recovery journal')
                candidate = root / 'releases' / transaction[key]
                verify_directory(candidate, args.origin, args.base_path, args.channel)
        current = pointer(root, args.channel, 'current')
        if current: require_backend_hooks(current, config)
        hook(config, 'quiescenceCommand', current, data, args.channel)
        restore(root, data, args.channel, transaction, config)
        audit(root, dict(transaction, status='recovered_to_old', completedAt=now()))
        pending.unlink(); sync_dir(pending.parent)
        return {'status': 'recovered_to_old', 'current': transaction['old']}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    b = sub.add_parser('build'); b.add_argument('--spec', required=True); b.add_argument('--output', required=True)
    for action in ('install', 'rollback', 'recover'):
        cmd = sub.add_parser(action)
        cmd.add_argument('--root', required=True); cmd.add_argument('--data-root', required=True)
        cmd.add_argument('--channel', choices=['preview', 'stable'], default='preview')
        cmd.add_argument('--origin', required=True); cmd.add_argument('--base-path', default='/')
        cmd.add_argument('--hooks')
        if action == 'install':
            cmd.add_argument('--bundle', required=True); cmd.add_argument('--sha256', required=True)
            cmd.add_argument('--allow-stable', action='store_true')
    s = sub.add_parser('status'); s.add_argument('--root', required=True)
    args = p.parse_args()
    try:
        if args.action == 'build': result = build_bundle(Path(args.spec).resolve(), Path(args.output))
        elif args.action in ('install', 'rollback', 'recover'): result = globals()[args.action](args)
        else:
            root = Path(args.root).resolve()
            result = {ch: {n: (str(pointer(root, ch, n)) if pointer(root, ch, n) else None) for n in ('current', 'previous')} | {'recoveryRequired': (root / 'channels' / ch / 'pending.json').exists()} for ch in ('stable', 'preview')}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError, tarfile.TarError) as e:
        detail = ('command failed; exit=' + str(e.returncode)) if isinstance(e, subprocess.CalledProcessError) else ('command timed out' if isinstance(e, subprocess.TimeoutExpired) else str(e))
        print('Release refused: ' + detail, file=sys.stderr); return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
