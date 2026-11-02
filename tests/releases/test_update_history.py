import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.check_update_history import check_commits, check_indexes, load_updates, render_index


class UpdateHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'docs/updates').mkdir(parents=True)

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.root, text=True, stderr=subprocess.DEVNULL).strip()

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-qm', message)
        return self.git('rev-parse', 'HEAD')

    def record(self, identity='20261103-0800-editable', commits=None):
        data = {'id': identity, 'version': '0.3.0-preview.2', 'date': '2026-11-03T08:00:00+08:00',
                'title': '分析可见并允许人工纠错', 'releaseState': 'source-only',
                'verificationState': 'not-recorded', 'commits': commits or []}
        content = '<!-- update-record: ' + json.dumps(data, ensure_ascii=False) + ' -->\n\n'
        for heading, text in [('为什么改', '分析结果不可见。'), ('这次改了什么', '显示结果并允许修改。'),
                              ('验证记录', '未执行浏览器验收。'), ('发布状态', '仅源码，未发布安装包。'),
                              ('关联位置', '实现提交由 Git 记录。')]:
            content += f'## {heading}\n\n{text}\n\n'
        path = self.root / 'docs/updates' / (identity + '.md')
        path.write_text(content)
        return path

    def test_history_keeps_original_version_and_unknown_verification(self):
        self.record()
        records = load_updates(self.root)
        self.assertEqual(records[0]['version'], '0.3.0-preview.2')
        self.assertEqual(records[0]['verificationState'], 'not-recorded')
        self.assertIn('未执行浏览器验收', records[0]['content'])
        self.assertIn('源码更新', render_index(records))

    def test_incomplete_record_and_duplicate_identity_fail(self):
        path = self.record()
        path.write_text(path.read_text().replace('## 验证记录', '## 其他'))
        with self.assertRaisesRegex(ValueError, '验证记录'):
            load_updates(self.root)
        path = self.record()
        (path.parent / '20261103-0900-copy.md').write_text(path.read_text())
        with self.assertRaisesRegex(ValueError, 'filename|Duplicate update ID'):
            load_updates(self.root)

    def test_github_rag_homepage_cannot_omit_the_latest_change(self):
        self.record()
        (self.root / 'docs/rag').mkdir()
        rag = self.root / 'docs/rag/README.md'
        rag.write_text('# RAG\n\n<!-- recent-updates:start -->\n<!-- recent-updates:end -->\n')
        records = load_updates(self.root)
        with self.assertRaisesRegex(ValueError, 'homepage is stale'):
            check_indexes(self.root, records)
        check_indexes(self.root, records, write=True)
        self.assertIn('显示结果并允许修改', rag.read_text())
        self.assertIn('../updates/20261103-0800-editable.md', rag.read_text())
        check_indexes(self.root, records)

    def test_git_coverage_catches_unrecorded_code_and_accepts_explicit_backfill(self):
        self.git('init', '-q')
        self.git('config', 'user.email', 'history-test@example.invalid')
        self.git('config', 'user.name', 'Synthetic history test')
        (self.root / 'README.md').write_text('synthetic baseline')
        baseline = self.commit('baseline')
        (self.root / 'docs/updates/policy.json').write_text(json.dumps({'baselineCommit': baseline}))
        (self.root / 'frontend').mkdir()
        source = self.root / 'frontend/editor.js'
        source.write_text('export const editable=true;')
        missing = self.commit('edit without update record')
        self.record()
        with self.assertRaisesRegex(ValueError, 'edit without update record'):
            check_commits(self.root, load_updates(self.root))
        # The historical change is explicitly linked, while this new record's
        # own commit is learned from Git without a circular self-SHA field.
        self.record(commits=[missing])
        source.write_text('export const editable=true; export const recoverable=true;')
        self.commit('new edit with its own update record')
        check_commits(self.root, load_updates(self.root))
        source.write_text('export const editable=false;')
        path = self.root / 'docs/updates/20261103-0800-editable.md'
        path.write_text(path.read_text() + '\n补改旧文档不能代替新迭代记录。\n')
        self.commit('another upgrade without new record')
        with self.assertRaisesRegex(ValueError, 'another upgrade without new record'):
            check_commits(self.root, load_updates(self.root))


if __name__ == '__main__':
    unittest.main()
