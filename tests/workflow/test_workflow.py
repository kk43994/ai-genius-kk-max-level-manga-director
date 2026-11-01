"""Synthetic workflow checks over module 3's REAL Store; never reads user data.

Before integration, set ASSET_LAB_STORAGE_REPO to module 3's isolated clone.
After cherry-picking storage, no environment variable is needed.
"""
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
import zipfile

import backend
if os.environ.get('ASSET_LAB_STORAGE_REPO'):
    backend.__path__.append(str(Path(os.environ['ASSET_LAB_STORAGE_REPO']) / 'backend'))

from backend.storage import Store
from backend.sessions import SessionService
from backend.workflow import WorkflowService, WorkflowRepository, WorkflowError, WorkflowOutputStore, register_routes
from backend.workflow.intake import decode_script, MAX_TEXT
from backend.workflow.service import inspect_image
from PIL import Image


def png(color=(40, 90, 60)):
    buffer = io.BytesIO()
    Image.new('RGB', (32, 24), color).save(buffer, 'PNG')
    return buffer.getvalue()


def encoded(name, content):
    return {'filename': name, 'contentBase64': base64.b64encode(content).decode()}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='asset-lab-workflow-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.key = secrets.token_bytes(32)
        self.storage = Store(self.root / 'data', encryption_key=self.key, release_root=self.root / 'release')
        self.sessions = SessionService(self.storage, public_origin='http://127.0.0.1:8898')
        self.ctx = self.sessions.create().context
        self.other = self.sessions.create().context
        self.repository = WorkflowRepository(self.storage)
        self.workflow = WorkflowService(self.repository)
        self.owner = {'tenantId': self.ctx.tenantId, 'provider': 'libtv', 'providerAccountId': 'pa_synthetic',
                      'providerIssuer': 'https://official.example', 'providerSubject': 'subject_synthetic',
                      'spaceId': 'space_personal', 'spaceKind': 'personal', 'accountLabelAtCreation': '合成账号',
                      'spaceNameAtCreation': '合成个人空间', 'boundAt': '2026-10-27T00:00:00Z'}
        self.project = self.workflow.create_project(self.ctx, {'name': '合成闭环', 'description': '无真实客户内容'})
        self.project_id = self.project['id']
        self.plan = self.workflow.save_plan(self.ctx, self.project_id, {'expectedVersion': 0, 'stylePrompt': '简洁电影风格',
            'entities': [{'id': f'ent_{category}', 'category': category, 'name': name, 'description': '测试设定', 'origin': 'manual'}
                         for category, name in [('character', '测试旅人'), ('scene', '测试庭院'), ('prop', '测试灯笼')]]})
        self.task_count = 0

    def task(self, recipe, entity='ent_character', source=None, owner=None, prompt='合成测试提示'):
        spec = self.workflow.build_spec(self.ctx, {'projectId': self.project_id, 'entityId': entity, 'recipe': recipe,
                'prompt': prompt, 'sourceRevisionIds': [source] if source else [], 'settings': {}}, owner or self.owner)
        self.task_count += 1
        return {**spec, 'id': f'task_synthetic_{self.task_count}', 'ownership': owner or self.owner, 'status': 'downloading',
                'providerReceipt': {'opaque': 'must_not_export'}, 'accessToken': 'synthetic-token-must-not-export'}

    def output(self, recipe, entity='ent_character', source=None, owner=None, color=(40, 90, 60)):
        task = self.task(recipe, entity, source, owner)
        return self.workflow.record_output(self.ctx, task, png(color))

    def asset(self, revision):
        return next(a for a in self.workflow.list_assets(self.ctx, self.project_id)['items'] if a['id'] == revision['assetId'])

    def review(self, revision, decision='approved', note='人工检查完毕'):
        return self.workflow.review(self.ctx, revision['assetId'], {'revisionId': revision['id'], 'sha256': revision['sha256'],
            'decision': decision, 'note': note, 'expectedVersion': self.asset(revision)['version']})['revision']

    def chain(self, entity='ent_character'):
        style = self.review(self.output('mj_style', entity))
        asset = self.review(self.output('image2_asset', entity, style['id']))
        refine = self.review(self.output('nano_refine', entity, asset['id']))
        return style, asset, refine

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(Exception) as raised:
            function(*args, **kwargs)
        self.assertEqual(getattr(raised.exception, 'code', None), code, str(raised.exception))
        return raised.exception

    def test_storyboard_accepts_multiple_reviewed_assets_and_keeps_lineage(self):
        refs=[self.chain(entity)[1] for entity in ('ent_character','ent_scene','ent_prop')]
        plan=self.workflow.get_plan(self.ctx,self.project_id)
        entities=[{k:v for k,v in e.items() if k in ('id','name','category','description','origin','variant','quote','scriptId')} for e in plan['entities']]
        entities.append({'id':'ent_shot','name':'镜头 001','category':'shot','origin':'manual'})
        self.workflow.save_plan(self.ctx,self.project_id,{'expectedVersion':plan['version'],'stylePrompt':plan['stylePrompt'],'entities':entities})
        payload={'projectId':self.project_id,'entityId':'ent_shot','recipe':'storyboard_image','prompt':'人物站在庭院手持灯笼','sourceRevisionIds':[r['id'] for r in refs],'settings':{'count':1}}
        checked=self.workflow.validate_task_inputs(self.ctx,payload,self.owner)
        self.assertEqual(len(checked['sources']),3)
        task={**payload,'id':'storyboard_task','ownership':self.owner,'status':'downloading','workflowSnapshot':checked['workflowSnapshot']}
        image=self.workflow.record_output(self.ctx,task,png())
        self.assertEqual(image['stage'],'storyboard');self.assertEqual(image['review'],'pending')
        self.assertEqual(image['sourceRevisionIds'],payload['sourceRevisionIds'])
        with self.assertRaises(WorkflowError):self.workflow.build_spec(self.ctx,payload,{**self.owner,'spaceId':'other'})
        with self.assertRaises(WorkflowError):self.workflow.build_spec(self.ctx,{**payload,'recipe':'image2_asset'},self.owner)
        self.review(refs[0],'changes_requested','人物衣服需要修改')
        with self.assertRaises(WorkflowError):self.workflow.validate_task_inputs(self.ctx,payload,self.owner)
        self.assertEqual(self.workflow.get_revision(self.ctx,image['id'],require_approved=False)['status'],'stale')

    def test_import_is_not_analysis_and_is_project_scoped(self):
        body = encoded('测试剧本.txt', '旅人来到庭院，拿起灯笼。'.encode())
        first = self.workflow.import_script(self.ctx, self.project_id, body)
        self.assertEqual(first['script']['analysisStatus'], 'not_started')
        self.assertFalse(first['script']['analysis']['configured'])
        second = self.workflow.import_script(self.ctx, self.project_id, body)
        self.assertTrue(second['duplicate'])
        another = self.workflow.create_project(self.ctx, {'name': '另一个合成项目'})
        third = self.workflow.import_script(self.ctx, another['id'], body)
        self.assertNotEqual(first['script']['id'], third['script']['id'])
        self.assert_error('NOT_FOUND', self.workflow.get_script, self.ctx, another['id'], first['script']['id'])
        self.assert_error('ANALYSIS_UNAVAILABLE', self.workflow.build_spec, self.ctx,
                          {'projectId': self.project_id, 'entityId': 'ent_character', 'recipe': 'script_analysis'}, self.owner)

    def test_manual_entities_exist_before_generation(self):
        assets = self.workflow.list_assets(self.ctx, self.project_id)
        self.assertEqual(len(assets['items']), 3)
        self.assertTrue(all(not a['revisionIds'] for a in assets['items']))
        self.assertFalse(assets['coverage']['complete'])

    def test_every_stage_requires_human_approval_and_cas_hash(self):
        style = self.output('mj_style')
        self.assertEqual(style['review'], 'pending')
        self.assert_error('VERSION_CONFLICT', self.task, 'image2_asset', source=style['id'])
        body = {'revisionId': style['id'], 'sha256': '0' * 64, 'decision': 'approved', 'note': '', 'expectedVersion': self.asset(style)['version']}
        self.assert_error('VERSION_CONFLICT', self.workflow.review, self.ctx, style['assetId'], body)
        body.update(sha256=style['sha256'], expectedVersion=1)
        self.assert_error('VERSION_CONFLICT', self.workflow.review, self.ctx, style['assetId'], body)
        self.review(style)
        asset = self.output('image2_asset', source=style['id'])
        self.assert_error('VERSION_CONFLICT', self.task, 'nano_refine', source=asset['id'])
        self.assert_error('VALIDATION_FAILED', self.review, asset, 'changes_requested', '')
        self.review(asset)
        self.assertEqual(self.output('nano_refine', source=asset['id'])['review'], 'pending')

    def test_full_three_entity_loop_archive_restart_and_safe_zip(self):
        for entity in ('ent_character', 'ent_scene', 'ent_prop'):
            self.chain(entity)
        self.assertEqual(self.workflow.list_assets(self.ctx, self.project_id)['coverage']['ready'], 3)
        raw, manifest = self.workflow.export(self.ctx, self.project_id)
        self.assertTrue(manifest['coverage']['complete'])
        self.assertEqual(len(manifest['assets']), 9)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIsNone(archive.testzip())
            for row in manifest['assets']:
                self.assertEqual(hashlib.sha256(archive.read(row['file'])).hexdigest(), row['sha256'])
                self.assertFalse(row['file'].startswith('/'))
                self.assertNotIn('..', Path(row['file']).parts)
            content = archive.read('资产清单.json').decode()
            for forbidden in ['accessToken', 'synthetic-token', 'providerReceipt', 'sourceFile', 'blobId', 'providerSubject', str(self.root)]:
                self.assertNotIn(forbidden, content)
        project = self.workflow.get_project(self.ctx, self.project_id)
        bundle = self.workflow.archive(self.ctx, self.project_id, {'expectedVersion': project['version']})
        reopened = Store(self.root / 'data', encryption_key=self.key, release_root=self.root / 'release')
        workflow = WorkflowService(WorkflowRepository(reopened))
        self.assertEqual(workflow.list_assets(self.ctx, self.project_id)['coverage']['ready'], 3)
        self.assertEqual(hashlib.sha256(workflow.bundle_content(self.ctx, self.project_id, bundle['id'])).hexdigest(), bundle['sha256'])

    def test_nano_repair_uses_original_image2_not_lossy_output(self):
        style, asset, refine = self.chain()
        self.review(refine, 'changes_requested', '细铜纹被洗糊，请保留原始结构')
        repaired = self.workflow.build_spec(self.ctx, {'projectId': self.project_id, 'entityId': 'ent_character', 'recipe': 'nano_refine',
            'prompt': '', 'sourceRevisionIds': [refine['id']], 'repairOfRevisionId': refine['id'], 'settings': {}}, self.owner)
        self.assertEqual(repaired['sourceRevisionIds'], [asset['id']])
        self.assertEqual(repaired['refineSourceRevisionId'], asset['id'])
        self.assertIn('细铜纹被洗糊', repaired['prompt'])
        self.assertNotIn(refine['id'], repaired['sourceRevisionIds'])

    def test_upstream_replacement_invalidates_downstream_and_export(self):
        style, asset, refine = self.chain()
        new_style = self.review(self.output('mj_style', color=(90, 90, 60)))
        rows = {r['id']: r for a in self.workflow.list_assets(self.ctx, self.project_id)['items'] for r in a['revisions']}
        self.assertEqual(rows[style['id']]['review'], 'superseded')
        self.assertEqual(rows[asset['id']]['status'], 'stale')
        self.assertEqual(rows[refine['id']]['status'], 'stale')
        self.assert_error('VERSION_CONFLICT', self.review, refine)
        _, manifest = self.workflow.export(self.ctx, self.project_id)
        self.assertEqual([r['revisionId'] for r in manifest['assets']], [new_style['id']])
        self.assertFalse(manifest['coverage']['complete'])

    def test_plan_edit_and_late_output_keep_stale_history(self):
        task = self.task('mj_style')
        changes = copy.deepcopy(self.plan)
        entities = [{k: v for k, v in e.items() if k != 'sourceRevision'} for e in changes['entities']]
        entities[0]['description'] = '设定已改为蓝色服装'
        self.workflow.save_plan(self.ctx, self.project_id, {'expectedVersion': self.plan['version'], 'entities': entities, 'stylePrompt': self.plan['stylePrompt']})
        late = self.workflow.record_output(self.ctx, task, png())
        self.assertEqual(late['status'], 'stale')
        self.assert_error('VERSION_CONFLICT', self.review, late)

    def test_owner_and_tenant_isolation_even_when_ui_selection_changes(self):
        style = self.review(self.output('mj_style'))
        other_owner = {**self.owner, 'providerAccountId': 'pa_other'}
        self.assert_error('OWNERSHIP_MISMATCH', self.task, 'image2_asset', source=style['id'], owner=other_owner)
        team_owner = {**self.owner, 'spaceId': 'space_team', 'spaceKind': 'team'}
        self.assert_error('OWNERSHIP_MISMATCH', self.task, 'image2_asset', source=style['id'], owner=team_owner)
        for operation, args in [(self.workflow.get_project, [self.project_id]), (self.workflow.list_assets, [self.project_id]),
                                (self.workflow.content, [style['assetId'], style['id']]), (self.workflow.export, [self.project_id])]:
            self.assert_error('NOT_FOUND', operation, self.other, *args)
        self.assertEqual(self.workflow.get_revision(self.ctx, style['id'])['ownership']['providerAccountId'], 'pa_synthetic')
        self.assert_error('VALIDATION_FAILED', self.workflow.create_project, self.ctx, {'name': '伪造', 'tenantId': self.other.tenantId})

    def test_quote_validation_and_project_cross_reference(self):
        script = self.workflow.import_script(self.ctx, self.project_id, encoded('原文.md', '旅人来到庭院。'.encode()))['script']
        bad = {'expectedVersion': self.plan['version'], 'stylePrompt': '', 'entities': [{
            'id': 'ent_quote', 'name': '旅人', 'category': 'character', 'origin': 'script', 'scriptId': script['id'], 'quote': '未出现的原文'}]}
        self.assert_error('VALIDATION_FAILED', self.workflow.save_plan, self.ctx, self.project_id, bad)
        bad['entities'][0]['quote'] = '旅人来到庭院。'
        saved = self.workflow.save_plan(self.ctx, self.project_id, bad)
        self.assertEqual(saved['entities'][0]['sourceRevision'], script['sourceRevision'])

    def test_output_replay_cannot_reset_review_or_overwrite_bytes(self):
        task = self.task('mj_style')
        first = self.workflow.record_output(self.ctx, task, png())
        self.review(first)
        repeated = self.workflow.record_output(self.ctx, task, png())
        self.assertEqual(first['id'], repeated['id'])
        self.assertEqual(repeated['review'], 'approved')
        self.assert_error('VERSION_CONFLICT', self.workflow.record_output, self.ctx, task, png((0, 0, 0)))
        self.assertEqual(len(self.asset(first)['revisionIds']), 1)

    def test_persistent_cas_detects_concurrent_edit(self):
        first = self.repository.transaction(self.ctx, write=True)
        a = first.__enter__()
        a.state['projects'][self.project_id]['name'] = '操作 A'
        current = self.workflow.get_project(self.ctx, self.project_id)
        self.workflow.update_project(self.ctx, self.project_id, {'name': '操作 B', 'expectedVersion': current['version']})
        self.assert_error('VERSION_CONFLICT', first.__exit__, None, None, None)
        self.assertEqual(self.workflow.get_project(self.ctx, self.project_id)['name'], '操作 B')

    def test_unsafe_uploads_and_docx_bombs_are_rejected(self):
        for filename in ['../x.txt', '/x.txt', 'C:\\x.txt', 'x\x00.txt', 'x.svg']:
            self.assert_error('VALIDATION_FAILED', decode_script, encoded(filename, b'test'))
        self.assert_error('VALIDATION_FAILED', decode_script, encoded('binary.txt', b'abc\x00'))
        self.assert_error('VALIDATION_FAILED', decode_script, encoded('large.txt', b'x' * (MAX_TEXT + 1)))
        for entry, content in [('word/document.xml', b'<!DOCTYPE x [<!ENTITY a "xx">]><x>&a;</x>'),
                               ('../escape', b'escape'), ('word/document.xml', b'x' * (2 * 1024 * 1024))]:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive: archive.writestr(entry, content)
            self.assert_error('VALIDATION_FAILED', decode_script, encoded('unsafe.docx', buffer.getvalue()))
        xml = b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic story.</w:t></w:r></w:p></w:body></w:document>'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive: archive.writestr('word/document.xml', xml)
        self.assertEqual(decode_script(encoded('safe.docx', buffer.getvalue()))[0]['text'], 'Synthetic story.')

    def test_bad_image_and_tampered_blob_cannot_be_approved_or_exported(self):
        self.assert_error('VALIDATION_FAILED', inspect_image, b'<svg onload="x"/>')
        self.assert_error('VALIDATION_FAILED', inspect_image, png()[:30])
        style = self.review(self.output('mj_style'))
        with self.repository.transaction(self.ctx) as tx:
            blob_id = tx.state['revisions'][style['id']]['blobId']
        blob_path = self.root / 'data' / 'tenants' / self.ctx.tenantId / 'blobs' / blob_id
        raw = blob_path.read_bytes(); blob_path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        self.assert_error('BLOB_INTEGRITY_FAILED', self.workflow.export, self.ctx, self.project_id)
        self.assert_error('BLOB_INTEGRITY_FAILED', self.review, style)

    def test_empty_or_partial_project_not_complete_archive(self):
        empty_project = self.workflow.create_project(self.ctx, {'name': '空项目'})
        self.assertFalse(self.workflow.list_assets(self.ctx, empty_project['id'])['coverage']['complete'])
        self.chain()
        project = self.workflow.get_project(self.ctx, self.project_id)
        self.assert_error('VERSION_CONFLICT', self.workflow.archive, self.ctx, self.project_id, {'expectedVersion': project['version']})

    def test_subpath_media_and_authenticated_route_gates(self):
        workflow = WorkflowService(self.repository, api_base='/asset-lab/api/v1')
        style = self.output('mj_style')
        result = workflow.get_revision(self.ctx, style['id'], require_approved=False)
        self.assertTrue(result['contentUrl'].startswith('/asset-lab/api/v1/'))
        class Router:
            def __init__(self): self.routes = {}
            def add(self, method, path, handler): self.routes[(method, path)] = handler
        router = Router(); register_routes(router, {'workflow': workflow})
        handler = router.routes[('POST', '/api/v1/projects')]
        self.assertEqual(handler({'tenantId': self.ctx.tenantId, 'csrfVerified': False, 'json': {'name': '拒绝'}}, {}).body['error']['code'], 'CSRF_FAILED')
        get = router.routes[('GET', '/api/v1/projects')]
        self.assertEqual(get({}, {}).body['error']['code'], 'SESSION_REQUIRED')
        self.assertEqual(get({'tenantId': self.ctx.tenantId}, {}).body['items'][0]['id'], self.project_id)

    def test_task_port_returns_snapshot_and_output_adapter_fails_closed(self):
        task = self.task('mj_style')
        spec = {k: task[k] for k in ('projectId','entityId','recipe','prompt','sourceRevisionIds','settings')}
        checked = self.workflow.validate_task_inputs(self.ctx, spec, self.owner)
        self.assertEqual(checked['workflowSnapshot']['entityVersion'], 1)
        class TaskRepository:
            def __init__(self, value): self.value=value
            def transaction(self, ctx): return self
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def get_task(self, identity): return self.value
        raw = png()
        material = {**task, 'spec': spec, 'inputs': checked}
        port = WorkflowOutputStore(self.workflow, TaskRepository(material))
        saved = port.put(self.ctx, task_id=task['id'], ownership=self.owner, index=0, content=raw, mime='image/png', sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(port.read(self.ctx, saved['blobId']), raw)
        material.pop('workflowSnapshot'); material['inputs'].pop('workflowSnapshot')
        self.assert_error('WORKFLOW_SNAPSHOT_MISSING', port.put, self.ctx, task_id=task['id'], ownership=self.owner, index=1, content=raw, mime='image/png', sha256=hashlib.sha256(raw).hexdigest())

    def test_video_never_produces_a_task(self):
        self.assert_error('GENERATION_DISABLED', self.task, 'video')
        self.assertFalse(self.workflow.capabilities()['videoGeneration'])


if __name__ == '__main__': unittest.main()
