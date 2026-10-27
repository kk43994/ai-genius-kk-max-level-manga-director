#!/usr/bin/env python3
"""Publish already-built, reviewed artifacts through the existing ssh kelao alias.

Default is read-only preflight. Never installs Nginx config or claims a URL live.
The fixed namespace is independent of all existing portal and customer services.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

HUB = '/srv/kk666/collaboration/bin/kk-agent-hub'
BASE = '/srv/asset-lab-customer'


def ssh(args, *, stdin=None, capture=False):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', 'kelao', shlex.join(args)],
                          input=stdin, check=True, capture_output=capture, timeout=900)


def hub(*args):
    ssh([HUB, *args])


def upload(path, remote):
    # Stream bytes through SSH; no remote shell expansion of caller input.
    with path.open('rb') as src:
        subprocess.run(['ssh', '-o', 'BatchMode=yes', 'kelao', 'cat > ' + shlex.quote(remote)], stdin=src, check=True, timeout=900)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['preflight', 'publish', 'rollback'], nargs='?', default='preflight')
    p.add_argument('--bundle'); p.add_argument('--sha256'); p.add_argument('--origin')
    p.add_argument('--base-path', default='/asset-lab/')
    p.add_argument('--channel', choices=['preview', 'stable'], default='preview')
    p.add_argument('--agent', default='operator-mac:codex:asset-release-' + uuid.uuid4().hex[:10])
    p.add_argument('--hooks', help='Existing reviewed remote hooks JSON, outside the release tree')
    p.add_argument('--allow-stable', action='store_true')
    p.add_argument('--acceptance', help='Local integration acceptance JSON for stable promotion')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9:._-]{1,128}', a.agent): p.error('Invalid agent ID')
    # Always read the authoritative operating rules and project state first.
    for file in ['/root/AGENTS.md', '/srv/kk666/collaboration/HANDOFF.md', '/srv/kk666/collaboration/PROTOCOL.md',
                 '/srv/kk666/collaboration/HUB.md', '/srv/kk666/collaboration/projects/sub2api-fleet/CURRENT.md']:
        ssh(['cat', file])
    ssh(['sh', '-c', 'if [ -f /srv/kk666/collaboration/projects/asset-lab-customer/CURRENT.md ]; then cat /srv/kk666/collaboration/projects/asset-lab-customer/CURRENT.md; fi'])
    ssh(['tail', '-n', '40', '/srv/kk666/collaboration/CHANGELOG.md'])
    state = json.loads(ssh([HUB, 'show', '--project', 'asset-lab-customer'], capture=True).stdout)
    active = [x for x in state.get('tasks', []) if x.get('status') not in ('done', 'cancelled')]
    print(json.dumps({'activeAssetLabTasks': active}, ensure_ascii=False, indent=2))
    if a.action == 'preflight':
        ssh(['sh', '-c', 'node --version; python3 --version; df -h /srv /var/lib; test ! -e /srv/asset-lab-customer/runtime || ls -ld /srv/asset-lab-customer/runtime'])
        return 0
    if active: p.error('An asset-lab Hub task is active; obtain an explicit handoff before publishing')
    if not a.origin: p.error('--origin required')
    if a.channel == 'stable' and not a.allow_stable: p.error('Stable requires --allow-stable')
    if a.action == 'publish':
        if not a.bundle or not a.sha256: p.error('publish requires --bundle and trusted --sha256')
        bundle = Path(a.bundle).resolve()
        with bundle.open('rb') as f: digest = hashlib.file_digest(f, 'sha256').hexdigest()
        if digest != a.sha256: p.error('Local artifact digest mismatch')
        if a.channel == 'stable':
            if not a.acceptance: p.error('Stable requires --acceptance from integration validation')
            acceptance = json.loads(Path(a.acceptance).read_text())
            if acceptance.get('bundleSha256') != digest or acceptance.get('integrationPassed') is not True or acceptance.get('customerReady') is not True:
                p.error('Stable acceptance must match this exact artifact and confirm readiness')
    task = 'asset-lab-release-' + uuid.uuid4().hex[:16]
    hub('register', '--agent', a.agent, '--machine', 'operator-mac', '--runtime', 'codex', '--project', 'asset-lab-customer', '--workdir', BASE, '--summary', 'Independent asset-lab release operation; no shared production routing changes')
    hub('task-create', '--id', task, '--project', 'asset-lab-customer', '--title', 'Asset lab ' + a.channel + ' ' + a.action, '--created-by', a.agent)
    hub('task-claim', '--id', task, '--agent', a.agent, '--summary', 'Own namespace only; release pointer journal is the rollback backup')
    try:
        tool = Path(__file__).with_name('release.py')
        tool_hash = hashlib.sha256(tool.read_bytes()).hexdigest()
        remote_tool = BASE + '/tools/' + tool_hash + '/release.py'
        ssh(['mkdir', '-p', BASE + '/incoming', str(Path(remote_tool).parent)])
        # Address tools by their digest; reject edits of an existing tool snapshot.
        exists = ssh(['sh', '-c', 'test ! -e ' + shlex.quote(remote_tool) + ' || sha256sum ' + shlex.quote(remote_tool)], capture=True).stdout.decode().strip()
        if exists and exists.split()[0] != tool_hash: raise ValueError('Remote tool digest mismatch')
        if not exists: upload(tool, remote_tool)
        observed = ssh(['sha256sum', remote_tool], capture=True).stdout.decode().split()[0]
        if observed != tool_hash: raise ValueError('Uploaded tool digest mismatch')
        cmd = ['python3', remote_tool, 'install' if a.action == 'publish' else 'rollback', '--root', BASE + '/runtime', '--data-root', '/var/lib/asset-lab-customer/' + a.channel, '--channel', a.channel, '--origin', a.origin, '--base-path', a.base_path]
        remote_bundle = None
        if a.action == 'publish':
            remote_bundle = BASE + '/incoming/' + task + '.tar.gz'
            upload(bundle, remote_bundle)
            cmd += ['--bundle', remote_bundle, '--sha256', digest]
            if a.allow_stable: cmd += ['--allow-stable']
        if a.hooks:
            if not re.fullmatch(r'/etc/asset-lab-customer/[A-Za-z0-9_.-]+\.json', a.hooks): raise ValueError('Hooks must be a reviewed file in /etc/asset-lab-customer/')
            cmd += ['--hooks', a.hooks]
        ssh(cmd)
        ssh(['python3', remote_tool, 'status', '--root', BASE + '/runtime'])
        ssh(['/srv/kk666/collaboration/append-change.sh', 'Asset lab ' + a.channel + ' ' + a.action + ' completed in isolated namespace', 'Bundle inventory and atomic switch verified; configured health hooks passed. Public routing is a separate integration step.', 'Use release.py rollback with the same runtime/data roots and reviewed hooks; never restore customer data'])
        hub('task-update', '--id', task, '--agent', a.agent, '--status', 'done', '--summary', 'Artifact switch verified; no Nginx or unrelated service changes')
        hub('heartbeat', '--agent', a.agent, '--status', 'done', '--summary', 'Asset lab release operation complete')
        if remote_bundle: ssh(['rm', '--', remote_bundle])
        return 0
    except (subprocess.SubprocessError, ValueError, OSError):
        ssh(['/srv/kk666/collaboration/append-change.sh', 'Asset lab release attempt failed in isolated namespace', 'Inspect pointer journal and health; success was not confirmed', 'Recover only the asset-lab pointer using its journal; never restore customer data'])
        hub('task-update', '--id', task, '--agent', a.agent, '--status', 'blocked', '--summary', 'Release command failed; inspect isolated pointer journal and health before any retry')
        hub('heartbeat', '--agent', a.agent, '--status', 'blocked', '--summary', 'Release requires inspection; no whole-data rollback')
        raise


if __name__ == '__main__':
    sys.exit(main())
