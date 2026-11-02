import copy
import io
import json
import unittest
import zipfile
import test_production as fixture
from backend.analysis.production import parse, validate, instruction
from backend.analysis.production_review import decode
from backend.workflow import WorkflowError


class DialogueOverrideTests(unittest.TestCase):
    setUp = fixture.ProductionTests.setUp
    begin = fixture.ProductionTests.begin
    finish = fixture.ProductionTests.finish

    def test_manual_edit_roundtrips_and_exports_original_separately(self):
        job = self.finish()
        source = copy.deepcopy(job['dialogues'])
        result = copy.deepcopy(job['result'])
        result['shots'][0]['dialogueOverrides'] = [{'id': 'dialogue_1', 'text': '这是用户改写的台词。', 'origin': 'manual'}]
        before = len(self.provider.submissions)
        updated = self.production.save_review(self.ctx, job['id'], {'expectedVersion': 0, 'expectedEditVersion': 0, 'result': result})
        self.assertEqual(updated['status'], 'ready')
        self.assertEqual(updated['dialogues'], source)
        raw, manifest = self.production.export_storyboard(self.ctx, job['id'])
        line = manifest['shots'][0]['dialogues'][0]
        self.assertEqual(line['text'], '这是用户改写的台词。')
        self.assertEqual(line['sourceText'], source[0]['text'])
        self.assertTrue(line['edited'])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertIn('人工改写 · 原文对照', archive.read('分镜脚本.html').decode())
        self.assertEqual(len(self.provider.submissions), before)

    def test_wrong_shot_duplicate_and_nonmanual_edits_rejected(self):
        for values in ([{'id':'dialogue_2','text':'错误镜头','origin':'manual'}],
                       [{'id':'dialogue_1','text':'重复','origin':'manual'}]*2,
                       [{'id':'dialogue_1','text':'冒充原文','origin':'source'}]):
            result = copy.deepcopy(self.result)
            result['shots'][0]['dialogueOverrides'] = values
            with self.assertRaises(WorkflowError):
                validate(result, self.script, self.context)

    def test_provider_cannot_forge_human_edits(self):
        result = copy.deepcopy(self.result)
        result['shots'][0]['dialogueOverrides'] = [{'id':'dialogue_1','text':'AI冒充人工','origin':'manual'}]
        text = json.dumps(result)
        with self.assertRaises(WorkflowError):
            parse(text, self.script, self.context)
        self.assertIsNone(decode(text))
        self.assertNotIn('dialogueOverrides', instruction(self.script, self.context))

    def test_metadata_added_deleted_order_roundtrip_and_export(self):
        job = self.finish()
        result = copy.deepcopy(job['result'])
        shot = result['shots'][0]
        shot['dialogueOverrides'] = [{'id':'dialogue_1','text':'编辑后的话','origin':'manual','speakerId':'char_ning','kind':'inner_monologue'}]
        shot['dialogueAdditions'] = [{'id':'line_new','text':'人工新增','origin':'manual','speakerId':None,'speakerLabel':'旁白员','kind':'narration'}]
        shot['dialogueOrder'] = ['line_new','dialogue_1']
        saved = self.production.save_review(self.ctx, job['id'], {'expectedVersion':0,'expectedEditVersion':0,'result':result})
        self.assertEqual(saved['status'],'ready')
        _, manifest = self.production.export_storyboard(self.ctx,job['id'])
        self.assertEqual([d['id'] for d in manifest['shots'][0]['dialogues']],['line_new','dialogue_1'])
        self.assertEqual(manifest['shots'][0]['dialogues'][1]['speakerName'],'阿宁')
        self.assertEqual(manifest['shots'][0]['dialogues'][1]['kind'],'inner_monologue')
        shot['dialogueOverrides'][0]['deleted'] = True
        shot['dialogueAdditions'][0].update(text='',deleted=True)
        saved = self.production.save_review(self.ctx,job['id'],{'expectedVersion':1,'expectedEditVersion':0,'result':result})
        self.assertEqual(saved['status'],'ready')
        _, manifest = self.production.export_storyboard(self.ctx,job['id'])
        self.assertEqual(manifest['shots'][0]['dialogues'],[])
        self.assertEqual(len(self.production.store.list(self.ctx,'production.review_history')['items']),1)

    def test_explicit_removed_shot_can_save_and_restore_but_ai_cannot_hide_omission(self):
        job = self.finish()
        result = copy.deepcopy(job['result'])
        result['removedShots'] = [result['shots'].pop(0)]
        result['shots'][0]['order'] = 1
        saved = self.production.save_review(self.ctx,job['id'],{'expectedVersion':0,'expectedEditVersion':0,'result':result})
        self.assertEqual(saved['status'],'ready')
        _, manifest = self.production.export_storyboard(self.ctx,job['id'])
        self.assertEqual(manifest['totalShots'],1)
        self.assertEqual(manifest['shots'][0]['id'],'shot_2')
        with self.assertRaises(WorkflowError): parse(json.dumps(result),self.script,self.context)
        self.assertIsNone(decode(json.dumps(result)))
        self.assertNotIn('removedShots',instruction(self.script,self.context))
        result['shots'].insert(0,result.pop('removedShots')[0]);result['shots'][1]['order']=2
        self.assertEqual(self.production.save_review(self.ctx,job['id'],{'expectedVersion':1,'expectedEditVersion':0,'result':result})['status'],'ready')

    def test_duplicate_added_ids_invalid_kind_and_unknown_speaker_are_not_accepted(self):
        for patch in ({'speakerId':'missing'},{'kind':'not_a_kind'},{'id':'dialogue_2'}):
            result=copy.deepcopy(self.result)
            result['shots'][0]['dialogueAdditions']=[{'id':'new_line','text':'新增','origin':'manual','speakerId':None,'speakerLabel':'手填人物','kind':'dialogue',**patch}]
            with self.assertRaises(WorkflowError):validate(result,self.script,self.context)
