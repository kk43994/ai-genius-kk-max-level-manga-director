"""Spatial master rules and compatibility with saved pre-master scene images."""
from unittest.mock import patch
import unittest
import test_production_coverage as fixture
from backend.workflow import WorkflowError


class SceneMasterTests(unittest.TestCase):
    setUp=fixture.CoverageTests.setUp
    finish=fixture.CoverageTests.finish
    begin=fixture.CoverageTests.begin
    image=fixture.CoverageTests.image
    save_entities=fixture.CoverageTests.save_entities
    complete=fixture.CoverageTests.complete

    def test_scene_state_requires_its_own_spatial_master(self):
        job=self.complete()
        scene=next(a for a in job['result']['assets'] if a['category']=='scene')
        bindings=[b for b in job['bindings'] if b['assetId']==scene['id']]
        master=next(b for b in bindings if b['stateId']=='__scene_master__')
        state=next(b for b in bindings if b['stateId']!='__scene_master__')
        revisions=self.workflow.list_assets(self.ctx,self.project['id'])['items']
        source=next(r for a in revisions if a['entityId']==master['entityId'] for r in a['revisions'] if r['stage']=='asset')
        output=self.image(state['entityId'],'image2_asset',[source['id']])
        self.assertEqual(output['sourceRevisionIds'],[source['id']])
        character=next(r for a in revisions if a['category']=='character' for r in a['revisions'] if r['stage']=='asset')
        with self.assertRaises(WorkflowError):self.image(state['entityId'],'image2_asset',[character['id']])

    def test_pre_master_scene_history_remains_valid_after_upgrade(self):
        job=self.complete()
        scene=next(a for a in job['result']['assets'] if a['category']=='scene')
        state=next(b for b in job['bindings'] if b['assetId']==scene['id'] and b['stateId']!='__scene_master__')
        # Emulate an image persisted by the older release, then evaluate it with
        # the actual upgraded rules. This does not change production behavior.
        with patch('backend.workflow.production_lineage.scene_state',return_value=False),patch('backend.workflow.production_lineage.image2_source_allowed',return_value=True):
            style=self.image(state['entityId'])
            old=self.image(state['entityId'],'image2_asset',[style['id']])
        revisions=self.workflow.list_assets(self.ctx,self.project['id'])['items']
        current=next(r for a in revisions for r in a['revisions'] if r['id']==old['id'])
        self.assertEqual(current['status'],'ready');self.assertEqual(current['review'],'approved')


    def test_existing_scene_style_shared_between_states_keeps_its_recorded_chain(self):
        from types import SimpleNamespace
        from backend.workflow.production_lineage import legacy_scene_source
        source={'id':'style-day','entityId':'day','stage':'style'}
        tx=SimpleNamespace(state={'revisions':{'night-output':{
            'entityId':'night','stage':'asset','sourceRevisionIds':['style-day']}}})
        self.assertTrue(legacy_scene_source(tx,'night',source))
        self.assertFalse(legacy_scene_source(tx,'new-state',source))
        self.assertFalse(legacy_scene_source(tx,'night',{**source,'id':'different-style'}))
