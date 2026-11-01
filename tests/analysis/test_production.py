"""Production design tests use synthetic provider output; no paid calls."""
import copy
import json
import unittest
import test_analysis as fixtures
from backend.analysis.production import ProductionService, validate, candidates, instruction
from backend.workflow import WorkflowError
from backend.storage import StorageError


class ProductionTests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.AnalysisTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        self.__dict__.update({k:v for k,v in fixture.__dict__.items() if not k.startswith('_')})
        self.analysis=fixture.finish()
        self.services.analysis=self.ai
        self.production=ProductionService(self.services,self.provider,enabled=True,background=False)
        self.context={'analysisId':self.analysis['id'],'analysis':self.analysis['result'],'aspectRatio':'9:16','stylePrompt':''}
        evidence={'startLine':1,'endLine':1,'quote':self.script['text'].splitlines()[0]}
        assets=[]
        for identity,category,name,source in [('a_lin','character','林舟',['char_lin']),('a_ning','character','阿宁',['char_ning']),('a_door','scene','书店',['loc_door']),('a_letter','prop','信封',[])]:
            assets.append({'id':identity,'category':category,'name':name,'sourceIds':source,'evidence':[evidence],
                'design':'设计建议，需人工核对','creativeChoices':['服装为创作建议'],
                'states':[{'id':'base','name':'基础状态','description':'保持原文状态','sceneIds':['scene_1'],
                    'imagePrompt':'单一物料独立展示，轮廓明确、光线均匀、保留身份与材质，按原文保持状态。'}]})
        shots=[]
        for i in (1,2):
            shots.append({'id':f'shot_{i}','sceneId':'scene_1','order':i,'durationSeconds':6,
                'purpose':'交接信封','beat':'交接','framing':'中景','camera':'固定机位','performance':'低声说话，听者注视信封',
                'startState':'手持信封','endState':'完成交接','references':[{'assetId':a['id'],'stateId':'base'} for a in assets],
                'dialogueIds':[f'dialogue_{i}'],'eventIds':[f'event_{i}'],
                'imagePrompt':'书店门口的两个人物以中景展示，信封位于两人之间，均匀傍晚光线。',
                'videoPrompt':'保持同一人物身份、服装和空间，持信的人伸手交接信封，镜头固定，另一人接住。',
                'sound':'保留原文对白与环境声','continuity':['信封持物手连续'],'evidence':[evidence]})
        self.result={'schemaVersion':'production-v1','sourceRevision':self.script['sourceRevision'],'analysisId':self.analysis['id'],
            'aspectRatio':'9:16','styleBible':'统一的二维漫剧美术建议','assets':assets,
            'scenePlans':[{'sceneId':'scene_1','locationAssetId':'a_door','spatialLayout':'两人站在门前','lighting':'傍晚光线','emotionalArc':'等待后释然','continuity':['视线连续']}],
            'shots':shots,'uncertainties':['服装需确认']}
        self.provider.text=json.dumps(self.result)
        self.provider.submissions=[]

    def begin(self,**kw):
        return self.production.start_plan(self.ctx,self.project['id'],self.script['id'],
            {**self.body,'analysisId':self.analysis['id'],'aspectRatio':'9:16',**kw})

    def finish(self):
        job=self.begin()
        self.production.advance(self.ctx,job['id']);self.production.advance(self.ctx,job['id'])
        return self.production.get(self.ctx,job['id'])

    def test_one_call_preserves_script_analysis_and_old_assets(self):
        before=self.workflow.get_plan(self.ctx,self.project['id'])
        job=self.finish()
        self.assertEqual(job['status'],'ready');self.assertEqual(job['totalCalls'],1)
        self.assertEqual(len(self.provider.submissions),1)
        self.assertEqual(self.workflow.get_plan(self.ctx,self.project['id']),before)
        self.assertEqual(job['dialogues'],self.analysis['result']['dialogues'])
        self.assertEqual(self.services.analysis.get(self.ctx,self.analysis['id'])['result'],self.analysis['result'])
        candidate=self.production.candidate(self.ctx,job['id'])
        self.assertEqual(candidate['addedCount'],4)
        self.workflow.save_plan(self.ctx,self.project['id'],{k:candidate[k] for k in ('expectedVersion','entities','stylePrompt')})
        self.assertEqual(self.production.candidate(self.ctx,job['id'])['addedCount'],0)
        self.assertTrue(all(b['saved'] for b in self.production.get(self.ctx,job['id'])['bindings']))

    def test_validation_rejects_missing_dialogue_wrong_refs_and_quotes(self):
        mutations=[lambda r:r['shots'][0].update(dialogueIds=[]),
                   lambda r:r['shots'][1].update(dialogueIds=['dialogue_1']),
                   lambda r:r['shots'][0]['references'][0].update(stateId='unknown'),
                   lambda r:r['assets'][0]['sourceIds'].append('mentioned-only'),
                   lambda r:r['shots'][0]['evidence'][0].update(quote='原文不存在'),
                   lambda r:r['shots'][1].update(eventIds=[]),
                   lambda r:r['shots'][1].update(order=1)]
        for mutate in mutations:
            result=copy.deepcopy(self.result);mutate(result)
            with self.assertRaises(WorkflowError):validate(result,self.script,self.context)

    def test_ambiguous_request_and_refresh_never_resubmit(self):
        job=self.begin();self.provider.ambiguous=True
        for _ in range(4):self.production.advance(self.ctx,job['id'])
        self.assertEqual(self.production.get(self.ctx,job['id'])['status'],'unknown_submission')
        self.assertEqual(len(self.provider.submissions),1)
        self.assertEqual(self.begin(idempotencyKey='different-double-click')['id'],job['id'])

    def test_invalid_output_stops_without_paid_repair(self):
        self.result['shots'][0]['dialogueIds']=[];self.provider.text=json.dumps(self.result)
        job=self.finish();self.assertEqual(job['status'],'needs_review');self.assertFalse(job['canResumeReview'])
        self.assertFalse(job['canRepairResult']);self.assertEqual(len(self.provider.submissions),1)

    def test_revalidation_reads_same_receipt_without_resubmission(self):
        self.result['shots'][0]['order']=2;self.provider.text=json.dumps(self.result)
        job=self.finish();self.assertTrue(job['canRevalidate'])
        receipt=copy.deepcopy(self.production._get(self.ctx,job['id'])['data']['steps'])
        self.result['shots'][0]['order']=1;self.provider.text=json.dumps(self.result)
        self.production.revalidate(self.ctx,job['id']);self.production.advance(self.ctx,job['id'])
        self.assertEqual(self.production.get(self.ctx,job['id'])['status'],'ready')
        self.assertEqual(self.production._get(self.ctx,job['id'])['data']['steps'],receipt)
        self.assertEqual(len(self.provider.submissions),1)
        with self.assertRaises(WorkflowError):self.production.revalidate(self.ctx,job['id'])

    def test_repair_is_one_explicit_extra_call_and_retains_original_receipt(self):
        self.result['shots'][0]['dialogueIds']=[];self.provider.text=json.dumps(self.result)
        job=self.finish();self.assertTrue(job['canRepairProduction'])
        original=self.production._get(self.ctx,job['id'])['data']['steps']['extract']
        with self.assertRaises(WorkflowError):self.production.repair_plan(self.ctx,job['id'],{})
        self.production.repair_plan(self.ctx,job['id'],{'confirmSpend':True})
        self.production.repair_plan(self.ctx,job['id'],{'confirmSpend':True})
        self.result['shots'][0]['dialogueIds']=['dialogue_1'];self.provider.text=json.dumps(self.result)
        self.production.advance(self.ctx,job['id']);self.production.advance(self.ctx,job['id'])
        result=self.production.get(self.ctx,job['id'])
        self.assertEqual(result['status'],'ready');self.assertEqual(result['completedCalls'],2)
        self.assertEqual(result['totalCalls'],2);self.assertEqual(len(self.provider.submissions),2)
        self.assertEqual(self.production._get(self.ctx,job['id'])['data']['steps']['extract'],original)
        self.assertNotIn('productionDraft',result)
        with self.assertRaises(WorkflowError):self.production.repair_plan(self.ctx,job['id'],{'confirmSpend':True})

    def test_per_scene_numbering_preserves_array_playback_order(self):
        context=copy.deepcopy(self.context);result=copy.deepcopy(self.result)
        second=copy.deepcopy(context['analysis']['scenes'][0]);second.update(id='scene_2',order=2)
        context['analysis']['scenes'].append(second)
        context['analysis']['dialogues'][1]['sceneId']='scene_2'
        context['analysis']['events'][1]['sceneId']='scene_2'
        scene=copy.deepcopy(result['scenePlans'][0]);scene['sceneId']='scene_2';result['scenePlans'].append(scene)
        for asset in result['assets']:asset['states'][0]['sceneIds'].append('scene_2')
        result['shots'][1].update(sceneId='scene_2',order=1)
        validate(result,self.script,context)
        result['shots'].reverse()
        with self.assertRaises(WorkflowError):validate(result,self.script,context)

    def test_edits_preserve_original_result_and_use_optimistic_version(self):
        job=self.finish();body={'expectedVersion':0,'shots':{'shot_1':{'durationSeconds':8,'performance':'停顿后交接'}}}
        edited=self.production.save_edits(self.ctx,job['id'],body)
        self.assertEqual(edited['result']['shots'][0]['durationSeconds'],8)
        self.assertEqual(self.production._get(self.ctx,job['id'])['data']['result']['shots'][0]['durationSeconds'],6)
        with self.assertRaises(WorkflowError):self.production.save_edits(self.ctx,job['id'],body)
        for patch in ({'dialogueIds':[]},{'durationSeconds':float('nan')},{'durationSeconds':0}):
            with self.assertRaises(WorkflowError):self.production.save_edits(self.ctx,job['id'],{'expectedVersion':1,'shots':{'shot_1':patch}})

    def test_tenant_and_source_boundaries(self):
        job=self.finish()
        for action in (lambda:self.production.get(self.other,job['id']),lambda:self.production.candidate(self.other,job['id']),
                       lambda:self.production.save_edits(self.other,job['id'],{'expectedVersion':0,'shots':{}})):
            with self.assertRaises((WorkflowError,StorageError)):action()
        plan=self.workflow.get_plan(self.ctx,self.project['id'])
        self.workflow.save_plan(self.ctx,self.project['id'],{'expectedVersion':plan['version'],'entities':plan['entities'],'stylePrompt':'different style'})
        self.assertTrue(self.production.get(self.ctx,job['id'])['stale'])
        with self.assertRaises(WorkflowError):self.production.candidate(self.ctx,job['id'])

    def test_asset_handoff_keeps_user_edits_and_numbered_names(self):
        job=self.finish();candidate=self.production.candidate(self.ctx,job['id'])
        candidate['entities'][0]['description']='用户设定'
        self.workflow.save_plan(self.ctx,self.project['id'],{k:candidate[k] for k in ('expectedVersion','entities','stylePrompt')})
        self.assertEqual(self.production.candidate(self.ctx,job['id'])['entities'][0]['description'],'用户设定')
        self.assertTrue(self.production.get(self.ctx,job['id'])['bindings'][0]['changed'])
        result=copy.deepcopy(self.result);result['assets'][1]['name']=result['assets'][0]['name']
        names=[r['name'] for r in candidates(result,self.script)]
        self.assertEqual(len(names),len(set(names)))

    def test_readable_invalid_draft_can_be_saved_then_corrected_without_ai(self):
        original_quote=self.result['assets'][0]['evidence'][0]['quote']
        # Deep-copy this quote because fixture evidence is shared by other rows.
        self.result['assets'][0]['evidence']=[{'startLine':1,'endLine':1,'quote':'缩写...'}]
        self.provider.text=json.dumps(self.result)
        job=self.finish();raw=copy.deepcopy(self.production._get(self.ctx,job['id'])['data'])
        self.assertEqual(job['status'],'needs_review')
        self.assertEqual(job['validationIssues'][0]['path'],'assets.0.evidence.0')
        self.assertEqual(job['validationIssues'][0]['sourceText'],original_quote)
        self.assertEqual(len(job['draftResult']['shots']),2)
        self.assertEqual(job['returnedText'],self.provider.text)
        with self.assertRaises(WorkflowError):self.production.candidate(self.ctx,job['id'])
        body={'expectedVersion':0,'expectedEditVersion':0,'result':job['draftResult']}
        saved=self.production.save_review(self.ctx,job['id'],body)
        self.assertEqual(saved['status'],'needs_review');self.assertEqual(saved['reviewVersion'],1)
        self.assertTrue(saved['manuallyEdited'])
        with self.assertRaises(WorkflowError):self.production.save_review(self.ctx,job['id'],body)
        edited=copy.deepcopy(saved['draftResult'])
        edited['assets'][0]['evidence'][0]['quote']=original_quote
        ready=self.production.save_review(self.ctx,job['id'],{'expectedVersion':1,'expectedEditVersion':0,'result':edited})
        self.assertEqual(ready['status'],'ready');self.assertEqual(ready['validationIssues'],[])
        self.assertEqual(self.production.candidate(self.ctx,job['id'])['addedCount'],4)
        self.assertEqual(len(self.provider.submissions),1)
        self.assertEqual(self.production._get(self.ctx,job['id'])['data'],raw)
        self.assertEqual(self.production.get(self.ctx,job['id'])['result'],edited)

    def test_manual_review_handles_structure_owner_stale_and_legacy_versions(self):
        job=self.finish()
        body={'expectedVersion':0,'expectedEditVersion':0,'result':copy.deepcopy(job['result'])}
        with self.assertRaises((WorkflowError,StorageError)):self.production.save_review(self.other,job['id'],body)
        broken=copy.deepcopy(body);broken['result']['shots'][0]['durationSeconds']='invalid'
        with self.assertRaises(WorkflowError):self.production.save_review(self.ctx,job['id'],broken)
        legacy=self.production.save_edits(self.ctx,job['id'],{'expectedVersion':0,'shots':{'shot_1':{'performance':'用户先修改表演'}}})
        with self.assertRaises(WorkflowError):self.production.save_review(self.ctx,job['id'],body)
        body.update(expectedEditVersion=legacy['editVersion'],result=legacy['result'])
        body['result']['shots'][0]['performance']='更新的表演'
        saved=self.production.save_review(self.ctx,job['id'],body)
        self.assertEqual(saved['result']['shots'][0]['performance'],'更新的表演')
        self.assertEqual(self.production._get(self.ctx,job['id'])['data']['result'],self.result)
        # Older clients may still edit shot fields after a whole-plan review.
        newer=self.production.save_edits(self.ctx,job['id'],{'expectedVersion':saved['editVersion'],'shots':{'shot_1':{'durationSeconds':9}}})
        self.assertEqual(newer['result']['shots'][0]['performance'],'更新的表演')
        self.assertEqual(newer['result']['shots'][0]['durationSeconds'],9)
        plan=self.workflow.get_plan(self.ctx,self.project['id'])
        self.workflow.save_plan(self.ctx,self.project['id'],{'expectedVersion':plan['version'],'entities':plan['entities'],'stylePrompt':'changed'})
        with self.assertRaises(WorkflowError):self.production.save_review(self.ctx,job['id'],body)

    def test_unparseable_output_is_still_visible_as_original_text(self):
        self.provider.text='{"shots": [unfinished'
        job=self.finish()
        self.assertEqual(job['status'],'failed');self.assertIsNone(job['draftResult'])
        self.assertEqual(job['returnedText'],self.provider.text)

    def test_prompt_separates_facts_design_and_generation(self):
        text=instruction(self.script,self.context)
        for value in ('creativeChoices','dialogueIds','单人独立参考图','不输出URL','表演','首尾状态'):
            self.assertIn(value,text)

if __name__=='__main__':unittest.main()
