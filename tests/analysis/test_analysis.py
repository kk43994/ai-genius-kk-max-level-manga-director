"""Synthetic tests; real-store durability and model failure behavior, no live calls."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.analysis.contract import parse_result, validate_result, asset_candidates, MAX_SOURCE_CHARACTERS
from backend.analysis.service import AnalysisService
from backend.storage import Store, StorageError
from backend.sessions import SessionService
from backend.workflow import WorkflowService, WorkflowRepository, WorkflowError
from backend.workflow.quickstart import start

EXAMPLE = json.loads((Path(__file__).resolve().parents[2]/'docs/screenplay-analysis-v1.example.json').read_text())

class FakeProvider:
    def __init__(self):
        self.submissions=[];self.owners=[];self.pending=False;self.ambiguous=False;self.text=None
    def preflight(self,ctx,owner):pass
    def bind(self,ctx,owner):
        self.owners.append(copy.deepcopy(owner));return self
    def prepare(self,job,script,save):save({'remoteProjectId':'synthetic-project'})
    def submit(self,job,script,save):
        step={'attempted':True,'taskId':None,'nodeId':None}
        save({'steps':{**job['steps'],job['phase']:step},'status':'submitting'})
        self.submissions.append((job['id'],job['phase']))
        if self.ambiguous:raise TimeoutError('upstream private details must never escape')
        return {**step,'taskId':'synthetic-'+job['phase'],'nodeId':'node-'+job['phase']}
    def read(self,job,step):
        if self.pending:return 'pending',None
        result=copy.deepcopy(EXAMPLE['result']);result['sourceRevision']=job['sourceRevision']
        return 'completed', self.text if self.text is not None else json.dumps(result)

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.key=secrets.token_bytes(32)
        self.store=Store(self.root/'data',encryption_key=self.key,release_root=self.root/'release')
        session=SessionService(self.store,public_origin='http://127.0.0.1:18881')
        self.ctx,self.other=session.create().context,session.create().context
        self.workflow=WorkflowService(WorkflowRepository(self.store))
        imported=start(self.workflow,self.ctx,{'text':EXAMPLE['sourceText'],'idempotencyKey':'analysis-test-import'})
        self.project,self.script=imported['project'],self.workflow.get_script(self.ctx,imported['project']['id'],imported['script']['id'])
        self.selected={'providerAccountId':'account-original','spaceId':'space-original','revision':1}
        self.owner={'tenantId':self.ctx.tenantId,'provider':'libtv','providerAccountId':'account-original',
            'providerSubject':'synthetic-subject','providerIssuer':'https://official.example',
            'spaceId':'space-original','spaceKind':'personal'}
        self.provider=FakeProvider()
        self.services=SimpleNamespace(storage=self.store,workflow=self.workflow,
            selections=SimpleNamespace(_get=lambda tx:self.selected),
            tasks=SimpleNamespace(_selection=lambda ctx:copy.deepcopy(self.selected),_owner=lambda ctx,sel:copy.deepcopy(self.owner)))
        self.ai=AnalysisService(self.services,self.provider,enabled=True,background=False)
        self.workflow.analysis=self.ai
        self.body={'idempotencyKey':'analysis-first-request','expectedSelectionRevision':1,'confirmSpend':True}
    def begin(self,**overrides):
        return self.ai.start(self.ctx,self.project['id'],self.script['id'],{**self.body,**overrides})
    def finish(self):
        job=self.begin()
        for _ in range(4):self.ai.advance(self.ctx,job['id'])
        return self.ai.get(self.ctx,job['id'])
    def test_import_performs_no_semantic_extraction(self):
        with patch('backend.workflow.script_plan.extract_plan',side_effect=AssertionError('local rules forbidden')):
            result=start(self.workflow,self.ctx,{'text':EXAMPLE['sourceText'],'idempotencyKey':'another-import-key'})
        self.assertEqual(result['plan']['entities'],[])
        self.assertEqual(result['script']['analysisStatus'],'not_started')
        self.assertFalse(self.workflow.capabilities()['localScriptExtraction'])
    def test_two_ai_passes_then_user_review_without_automatic_plan_changes(self):
        before=self.workflow.get_plan(self.ctx,self.project['id'])
        job=self.finish();self.assertEqual(job['status'],'ready');self.assertEqual(job['completedCalls'],2)
        self.assertEqual([phase for _,phase in self.provider.submissions],['extract','review'])
        self.assertEqual(self.workflow.get_plan(self.ctx,self.project['id']),before)
        candidate=self.ai.candidate(self.ctx,job['id']);self.assertEqual(len(candidate['entities']),3)
        saved=self.workflow.save_plan(self.ctx,self.project['id'],{k:candidate[k] for k in ('expectedVersion','entities','stylePrompt')})
        self.assertEqual(len(saved['entities']),3)
        self.assertFalse(saved.get('needsReview', False))
    def test_duplicate_start_read_and_refresh_do_not_submit(self):
        job=self.begin();self.assertEqual(self.begin()['id'],job['id'])
        self.assertEqual(self.begin(idempotencyKey='second-click-key')['id'],job['id'])
        self.ai.get(self.ctx,job['id']);self.ai.refresh(self.ctx,job['id'])
        self.assertEqual(self.provider.submissions,[])
        self.ai.advance(self.ctx,job['id']);self.provider.pending=True
        self.ai.advance(self.ctx,job['id']);self.ai.advance(self.ctx,job['id'])
        self.assertEqual(len(self.provider.submissions),1)
    def test_restart_recovers_original_receipt_and_owner(self):
        job=self.begin();self.ai.advance(self.ctx,job['id'])
        self.selected.update(providerAccountId='other-account',spaceId='other-space',revision=2)
        store=Store(self.root/'data',encryption_key=self.key,release_root=self.root/'release')
        self.services.storage=store
        restarted=AnalysisService(self.services,self.provider,enabled=True,background=False)
        for _ in range(3):restarted.advance(self.ctx,job['id'])
        self.assertEqual(restarted.get(self.ctx,job['id'])['status'],'ready')
        self.assertEqual(len(self.provider.submissions),2)
        self.assertTrue(all(owner==self.owner for owner in self.provider.owners))
    def test_ambiguous_submission_never_retries(self):
        job=self.begin();self.provider.ambiguous=True;self.ai.advance(self.ctx,job['id'])
        for _ in range(3):self.ai.advance(self.ctx,job['id'])
        result=self.ai.get(self.ctx,job['id'])
        self.assertEqual(result['status'],'unknown_submission');self.assertFalse(result['canRetry'])
        self.assertEqual(len(self.provider.submissions),1)
        self.assertNotIn('private',json.dumps(result))
    def test_tenant_isolation_for_all_analysis_operations(self):
        job=self.begin()
        for call in (lambda:self.ai.get(self.other,job['id']),lambda:self.ai.refresh(self.other,job['id']),
                     lambda:self.ai.candidate(self.other,job['id']),lambda:self.ai.latest(self.other,self.project['id'],self.script['id'])):
            with self.assertRaises((StorageError,WorkflowError)) as error:call()
            self.assertEqual(error.exception.status,404)
    def test_changed_selection_and_missing_spend_confirmation_rejected_before_submission(self):
        for overrides,code in (({'confirmSpend':False},'ANALYSIS_SPEND_CONFIRMATION_REQUIRED'),
                               ({'expectedSelectionRevision':0},'SELECTION_CHANGED')):
            with self.assertRaises(WorkflowError) as error:self.begin(**overrides)
            self.assertEqual(error.exception.code,code)
        self.assertFalse(self.provider.submissions)
    def test_disabled_analysis_never_falls_back_to_rules(self):
        self.ai.enabled=False
        with self.assertRaises(WorkflowError) as error:self.begin()
        self.assertEqual(error.exception.code,'ANALYSIS_UNAVAILABLE')
        self.assertEqual(self.workflow.get_plan(self.ctx,self.project['id'])['entities'],[])
    def test_long_source_is_saved_whole_and_not_sent_partially(self):
        text='剧本正文。'*4000
        source=self.workflow.import_script(self.ctx,self.project['id'],{'filename':'长剧本.txt','contentBase64':base64.b64encode(text.encode()).decode()})['script']
        with self.assertRaises(WorkflowError) as error:self.ai.start(self.ctx,self.project['id'],source['id'],self.body)
        self.assertEqual(error.exception.code,'ANALYSIS_SOURCE_TOO_LARGE')
        self.assertEqual(self.workflow.get_script(self.ctx,self.project['id'],source['id'])['text'],text)
        self.assertFalse(self.provider.submissions)
    def test_partial_or_malformed_model_output_fails_and_leaves_plan(self):
        job=self.begin();self.ai.advance(self.ctx,job['id']);self.provider.text='{"complete":'
        self.ai.advance(self.ctx,job['id'])
        result=self.ai.get(self.ctx,job['id']);self.assertEqual(result['status'],'failed')
        self.assertIsNone(result['result']);self.assertTrue(result['canRetry'])
        self.assertEqual(len(self.provider.submissions),1)
        with self.assertRaises(WorkflowError):self.ai.candidate(self.ctx,job['id'])
    def test_completed_job_requires_explicit_new_analysis_and_new_key(self):
        job=self.finish();self.assertEqual(self.begin()['id'],job['id'])
        new=self.begin(idempotencyKey='explicit-reanalysis',reanalyze=True)
        self.assertNotEqual(new['id'],job['id']);self.assertEqual(new['status'],'preparing')
    def test_lease_prevents_concurrent_double_submission(self):
        job=self.begin()
        with self.store.transaction(self.ctx) as tx:
            row=tx.get('analysis.jobs',job['id']);data=row['data'];data['lease']={'token':'other-worker','until':9999999999}
            tx.update('analysis.jobs',job['id'],data,expected_version=row['version'])
        self.ai.advance(self.ctx,job['id']);self.assertFalse(self.provider.submissions)
    def test_valid_source_contract_and_fenced_json(self):
        result=copy.deepcopy(EXAMPLE['result']);result['sourceRevision']=self.script['sourceRevision']
        self.assertEqual(parse_result('```json\n'+json.dumps(result)+'\n```',self.script),result)
    def test_source_evidence_dialogue_links_and_coverage_are_verified(self):
        changes=[lambda r:r['dialogues'][0].update(text='虚构台词'),lambda r:r['dialogues'][0].update(speakerId='missing_person'),
                 lambda r:r['characters'][0]['evidence'][0].update(quote='伪造原文'),lambda r:r['coverage'].update(processedRanges=[{'startLine':1,'endLine':1}]),
                 lambda r:r.update(sourceRevision='different-source'),lambda r:r.update(complete=False)]
        for mutate in changes:
            with self.subTest(mutate=mutate):
                result=copy.deepcopy(EXAMPLE['result']);result['sourceRevision']=self.script['sourceRevision'];mutate(result)
                with self.assertRaises(WorkflowError):validate_result(result,self.script)
