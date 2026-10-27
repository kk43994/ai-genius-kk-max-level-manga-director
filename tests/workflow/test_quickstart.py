import base64
import secrets
import io
import zipfile
import json
import tempfile
import unittest
from pathlib import Path

from backend.storage import Store
from backend.sessions import SessionService
from backend.workflow import WorkflowService, WorkflowRepository, WorkflowError
from backend.workflow.quickstart import start, analyze
from backend.workflow.script_plan import extract_plan

SCRIPT = '''《山间来信》
角色：林舟、阿宁
场景：旧书店
道具：信封
视觉风格：黑白漫画，细腻线条。
1-1 旧书店 内 日
林舟（低声）：这封信，是留给你的。
阿宁：我等了很久。
'''


class QuickStartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        self.key = secrets.token_bytes(32)
        self.store = Store(self.path/'data', encryption_key=self.key, release_root=self.path/'release')
        self.sessions = SessionService(self.store, public_origin='http://127.0.0.1:18881')
        self.ctx, self.other = self.sessions.create().context, self.sessions.create().context
        self.workflow = WorkflowService(WorkflowRepository(self.store))
        self.payload = {'text': SCRIPT, 'idempotencyKey': 'quickstart-synthetic-001'}

    def test_one_input_creates_project_source_and_deduplicated_assets_atomically(self):
        result = start(self.workflow, self.ctx, self.payload)
        self.assertEqual(result['project']['name'], '山间来信')
        entities = result['plan']['entities']
        self.assertEqual([(e['category'], e['name']) for e in entities],
                         [('character', '林舟'), ('character', '阿宁'), ('scene', '旧书店'), ('prop', '信封')])
        self.assertTrue(result['plan']['needsReview'])
        self.assertTrue(all(e['quote'] in SCRIPT and e['scriptId'] == result['script']['id'] for e in entities))
        assets = self.workflow.list_assets(self.ctx, result['project']['id'])
        self.assertEqual(len(assets['items']), 4)
        self.assertFalse(assets['coverage']['complete'])
        self.assertTrue(all(not a['revisions'] for a in assets['items']))

    def test_lost_response_and_restart_resume_same_project(self):
        result = start(self.workflow, self.ctx, self.payload)
        second_store = Store(self.path/'data', encryption_key=self.key, release_root=self.path/'release')
        restarted = WorkflowService(WorkflowRepository(second_store))
        duplicate = start(restarted, self.ctx, self.payload)
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(result['project']['id'], duplicate['project']['id'])
        self.assertEqual(len(restarted.list_projects(self.ctx)['items']), 1)

    def test_key_reuse_cannot_overwrite_script_and_tenant_keys_are_isolated(self):
        first = start(self.workflow, self.ctx, self.payload)
        with self.assertRaises(WorkflowError) as raised:
            start(self.workflow, self.ctx, {**self.payload, 'text': SCRIPT+'\n道具：另一封信'})
        self.assertEqual(raised.exception.code, 'IDEMPOTENCY_CONFLICT')
        second = start(self.workflow, self.other, self.payload)
        self.assertNotEqual(first['project']['id'], second['project']['id'])

    def test_rule_extraction_is_not_claimed_for_unstructured_prose(self):
        result = extract_plan('他走进房间，回忆起很久以前的故事。')
        self.assertEqual(result['entities'], [])
        self.assertEqual(result['analysis']['status'], 'needs_review')
        self.assertIn('未识别', result['analysis']['warnings'][0])
        for label in ('旁白', '字幕', '音效', '镜头'):
            self.assertEqual(extract_plan(label+'：一阵脚步声。')['entities'], [])

    def test_numbered_shot_and_scene_labels_are_not_characters(self):
        text = '场景一：山间小亭 外景 日\n镜头A：镜头推近。\n镜头1：他站起身。\n闪回1：往日的庭院。\n叶宇：我来了。'
        entities = extract_plan(text)['entities']
        self.assertEqual([(e['category'],e['name']) for e in entities],
                         [('scene','山间小亭'),('character','叶宇')])
        self.assertTrue(all(e['quote'] in text for e in entities))

    def test_character_definition_keeps_full_appearance_without_splitting_commas(self):
        definition='九天阁大师兄，身形挺拔，黑发垂落，神态散漫慵懒。'
        for script in ('人物：\n叶宇：'+definition+'\n\n叶宇：不必紧张。', '角色：叶宇：'+definition):
            entities=extract_plan(script)['entities']
            self.assertEqual(len(entities),1)
            self.assertEqual(entities[0]['name'],'叶宇')
            self.assertEqual(entities[0]['description'],definition)
            self.assertIn(entities[0]['quote'],script)

    def test_reanalysis_preview_never_overwrites_existing_plan(self):
        result=start(self.workflow,self.ctx,self.payload)
        pid,sid=result['project']['id'],result['script']['id']
        before=self.workflow.get_plan(self.ctx,pid)
        preview=analyze(self.workflow,self.ctx,pid,sid,{'preview':True})
        self.assertEqual(preview['expectedVersion'],before['version'])
        self.assertEqual(self.workflow.get_plan(self.ctx,pid),before)

    def test_manual_confirmation_is_persisted_and_retry_does_not_reset_it(self):
        result = start(self.workflow, self.ctx, self.payload)
        entities = [{k:v for k,v in e.items() if k!='sourceRevision'} for e in result['plan']['entities']]
        saved = self.workflow.save_plan(self.ctx, result['project']['id'], {'expectedVersion': 1,
            'entities': entities, 'stylePrompt': result['plan']['stylePrompt']})
        self.assertFalse(saved.get('needsReview', False))
        retried = start(self.workflow, self.ctx, self.payload)
        self.assertEqual(retried['plan']['version'], 2)
        self.assertFalse(retried['plan'].get('needsReview', False))

    def test_file_start_and_invalid_input_leave_no_partial_project(self):
        result = start(self.workflow, self.ctx, {'filename': '中文剧本.txt',
            'contentBase64': base64.b64encode(SCRIPT.encode()).decode(), 'idempotencyKey':'file-start-001'})
        self.assertEqual(len(result['plan']['entities']), 4)
        for body in ({'text':'', 'idempotencyKey':'bad-start-001'},
                     {'text':SCRIPT, 'filename':'../剧本.txt', 'idempotencyKey':'bad-start-002'},
                     {'text':SCRIPT, 'idempotencyKey':'bad-start-003', 'contentBase64':'eA=='}):
            with self.assertRaises(WorkflowError):
                start(self.workflow, self.ctx, body)
        self.assertEqual(len(self.workflow.list_projects(self.ctx)['items']), 1)

    def test_synthetic_script_to_reviewed_archive_uses_real_store_and_hashes(self):
        import test_workflow as fixtures
        result = start(self.workflow, self.ctx, self.payload)
        pid, plan = result['project']['id'], result['plan']
        owner = {'tenantId': self.ctx.tenantId, 'provider':'libtv', 'providerAccountId':'synthetic-account',
                 'providerSubject':'synthetic-subject', 'spaceId':'synthetic-space', 'spaceKind':'personal'}
        sample_spec = {'projectId':pid, 'entityId':plan['entities'][0]['id'], 'recipe':'mj_style',
                       'prompt':'合成验证，不发起真实生成', 'sourceRevisionIds':[], 'settings':{'count':1}}
        with self.assertRaises(WorkflowError) as raised:
            self.workflow.build_spec(self.ctx, sample_spec, owner)
        self.assertEqual(raised.exception.code, 'PLAN_REVIEW_REQUIRED')
        clean = [{k:v for k,v in e.items() if k!='sourceRevision'} for e in plan['entities']]
        self.workflow.save_plan(self.ctx, pid, {'expectedVersion':1, 'entities':clean, 'stylePrompt':plan['stylePrompt']})
        for entity in clean:
            source = None
            for stage in ('mj_style','image2_asset','nano_refine'):
                spec = self.workflow.build_spec(self.ctx, {**sample_spec, 'entityId':entity['id'],
                    'recipe':stage, 'sourceRevisionIds':[source] if source else []}, owner)
                task = {**spec, 'id':'synthetic-'+entity['id']+'-'+stage, 'ownership':owner, 'status':'downloading'}
                revision = self.workflow.record_output(self.ctx, task, fixtures.png())
                self.assertEqual(revision['review'], 'pending')
                asset = next(a for a in self.workflow.list_assets(self.ctx,pid)['items'] if a['id']==revision['assetId'])
                self.workflow.review(self.ctx, asset['id'], {'revisionId':revision['id'], 'sha256':revision['sha256'],
                    'decision':'approved','note':'合成图片技术验证，不代表创意批准','expectedVersion':asset['version']})
                source = revision['id']
        self.assertTrue(self.workflow.list_assets(self.ctx,pid)['coverage']['complete'])
        project = self.workflow.get_project(self.ctx,pid)
        bundle = self.workflow.archive(self.ctx,pid,{'expectedVersion':project['version']})
        self.assertEqual(len(bundle['revisionIds']),12)
        self.assertEqual(bundle['planVersion'],2)
        raw = self.workflow.bundle_content(self.ctx,pid,bundle['id'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(len([n for n in archive.namelist() if n.endswith('.png')]),12)

    def test_existing_project_analysis_requires_review_and_never_overwrites_plan(self):
        project = self.workflow.create_project(self.ctx, {'name':'已有项目'})
        imported = self.workflow.import_script(self.ctx, project['id'], {'filename':'剧本.txt',
            'contentBase64':base64.b64encode(SCRIPT.encode()).decode()})
        plan = analyze(self.workflow, self.ctx, project['id'], imported['script']['id'], {'expectedVersion':0})
        self.assertTrue(plan['needsReview'])
        with self.assertRaises(WorkflowError) as raised:
            analyze(self.workflow, self.ctx, project['id'], imported['script']['id'], {'expectedVersion':1})
        self.assertEqual(raised.exception.code, 'PLAN_EXISTS')
