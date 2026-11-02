#!/usr/bin/env python3
"""Validate and index per-iteration change records, with optional Git coverage."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ('为什么改', '这次改了什么', '验证记录', '发布状态', '关联位置')
RELEASES = {'source-only', 'candidate-build', 'release-preparation', 'published-evidence', 'plan-only', 'verification-only'}


def load_updates(root=ROOT):
    records, identities, commits = [], set(), set()
    for path in sorted((root / 'docs/updates').glob('[0-9]*.md')):
        content = path.read_text()
        match = re.search(r'^<!-- update-record: (.+) -->$', content, re.M)
        if not match:
            raise ValueError(f'Missing update metadata: {path.name}')
        data = json.loads(match[1])
        for field in ('id', 'version', 'date', 'title', 'releaseState', 'verificationState'):
            if not isinstance(data.get(field), str) or not data[field].strip():
                raise ValueError(f'Missing {field}: {path.name}')
        if datetime.fromisoformat(data['date']).tzinfo is None:
            raise ValueError(f'Update timestamp requires a timezone: {path.name}')
        if path.stem != data['id']:
            raise ValueError(f'Update ID must match its filename: {path.name}')
        if data['id'] in identities:
            raise ValueError(f'Duplicate update ID: {data["id"]}')
        identities.add(data['id'])
        if data['releaseState'] not in RELEASES or data['verificationState'] not in ('recorded', 'not-recorded'):
            raise ValueError(f'Invalid verification/release state: {path.name}')
        if not isinstance(data.get('commits'), list):
            raise ValueError(f'Missing commit list: {path.name}')
        for commit in data['commits']:
            if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
                raise ValueError(f'Invalid exact commit: {path.name}')
            if commit in commits:
                raise ValueError(f'Commit recorded twice: {commit}')
            commits.add(commit)
        for heading in SECTIONS:
            section = re.search(r'^## ' + heading + r'\n(.*?)(?=^## |\Z)', content, re.M | re.S)
            if not section or not section[1].strip() or section[1].strip() in ('TODO', '待填写'):
                raise ValueError(f'Missing substantive section {heading}: {path.name}')
        records.append({**data, 'file': path.relative_to(root).as_posix(), 'content': content})
    if not records:
        raise ValueError('No per-iteration update records')
    return sorted(records, key=lambda r: (datetime.fromisoformat(r['date']).timestamp(), r['id']), reverse=True)


def render_index(records):
    labels = {'source-only': '源码更新', 'candidate-build': '候选构建', 'release-preparation': '发布准备',
              'published-evidence': '公开发布证据', 'plan-only': '计划登记', 'verification-only': '验收补记'}
    text = ['# 每次升级记录', '',
            '按时间倒序记录；历史项使用原 Git 提交时间，新记录随实现提交保存。每条都说明为什么改、改了什么、验证结果和发布状态；同一个开发版本内的多次升级分别登记。', '',
            '历史回填从工作台重构基线开始，依据 Git 差异和当时文档；没有独立验证证据的记录明确标为未记录。源码更新不等于安装包已发布，也不等于客户电脑已升级。', '',
            f'当前收录 **{len(records)} 次迭代**。点击升级内容查看完整说明及对应提交。', '',
            '| 时间（北京时间） | 源码版本 | 这次升级的内容 | 状态 |', '| --- | --- | --- | --- |']
    for r in records:
        date = datetime.fromisoformat(r['date']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M')
        text.append(f'| {date} | {r["version"]} | [{r["title"]}]({Path(r["file"]).name}) | {labels[r["releaseState"]]} |')
    text += ['', '## 后续如何登记', '',
             '复制 [记录模板](TEMPLATE.md)，在本次代码提交中新增一条记录。实现提交可留空，由 Git 中文件的首次加入提交确定，避免预填不存在的提交号。回填旧记录时填写完整的真实提交号。', '',
             '`python scripts/check_update_history.py --render` 更新本目录；`python scripts/query_project_knowledge.py --updates --limit 5` 查看最近五次升级；加 `--version 0.3.0-preview.6` 按源码版本筛选。', '',
             'CI 核对历史覆盖：新的程序、测试、构建或检查脚本提交缺少对应升级记录时失败。正文必须保留真实验证与发布状态；检查只能发现缺项，不能替人判断功能质量。', '']
    return '\n'.join(text)


def render_rag_recent(records):
    lines = ['<!-- recent-updates:start -->', '## 最近更新', '',
             'GitHub 的 RAG 首页直接列出本次升级内容；完整历史见 [每次升级记录](../updates/README.md)。下列源码更新不代表公共安装包已发布。', '',
             '| 时间（北京时间） | 这次更新了什么 | 源码版本 |', '| --- | --- | --- |']
    for record in records[:8]:
        section = re.search(r'^## 这次改了什么\n(.*?)(?=^## |\Z)', record['content'], re.M | re.S)[1].strip()
        summary = section.splitlines()[0].removeprefix('- ').replace('|', '\\|')
        title = record['title'].replace('|', '\\|')
        date = datetime.fromisoformat(record['date']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H:%M')
        lines.append(f'| {date} | [{title}](../updates/{Path(record["file"]).name})<br>{summary} | {record["version"]} |')
    return '\n'.join(lines + ['', '<!-- recent-updates:end -->'])


def check_indexes(root, records, write=False):
    index = root / 'docs/updates/README.md'
    expected = render_index(records)
    rag = root / 'docs/rag/README.md'
    source = rag.read_text()
    marker = r'<!-- recent-updates:start -->.*?<!-- recent-updates:end -->'
    if not re.search(marker, source, re.S):
        raise ValueError('RAG homepage is missing its recent-updates section')
    rag_expected = re.sub(marker, lambda _: render_rag_recent(records), source, flags=re.S)
    if write:
        index.write_text(expected)
        rag.write_text(rag_expected)
    elif not index.is_file() or index.read_text() != expected or source != rag_expected:
        raise ValueError('Upgrade timeline or GitHub RAG homepage is stale; run scripts/check_update_history.py --render')


def check_commits(root, records):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True).strip()
    if git('rev-parse', '--is-shallow-repository') == 'true':
        raise ValueError('Update coverage requires full history (checkout fetch-depth: 0)')
    policy = json.loads((root / 'docs/updates/policy.json').read_text())
    baseline = policy['baselineCommit']
    git('cat-file', '-e', baseline + '^{commit}')
    covered = {c for r in records for c in r['commits']}
    for c in covered:
        git('cat-file', '-e', c + '^{commit}')
    for record in records:
        # A new record travels with its code commit; its hash is learned from Git.
        creation = git('log', '--follow', '--diff-filter=A', '--format=%H', '--', record['file']).splitlines()
        covered.update(creation)
    missing = []
    protected = ('frontend/', 'backend/', 'local_client/', 'scripts/', 'deploy/', 'tests/', '.github/')
    for commit in git('rev-list', '--reverse', '--no-merges', baseline + '..HEAD').splitlines():
        paths = git('diff-tree', '--no-commit-id', '--name-only', '-r', commit).splitlines()
        meaningful = any(p.startswith(protected) or p in ('requirements.txt', 'AGENTS.md') for p in paths)
        if meaningful and commit not in covered:
            missing.append(git('show', '-s', '--format=%h %s', commit))
    if missing:
        raise ValueError('Missing per-iteration update record:\n' + '\n'.join(missing))
    return len(covered)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--check-commits', action='store_true')
    args = parser.parse_args()
    try:
        records = load_updates()
        check_indexes(ROOT, records, write=args.render)
        covered = check_commits(ROOT, records) if args.check_commits else None
        print(json.dumps({'valid': True, 'iterations': len(records), 'coveredCommits': covered}))
    except (ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))


if __name__ == '__main__':
    main()
