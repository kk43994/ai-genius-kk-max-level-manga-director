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
