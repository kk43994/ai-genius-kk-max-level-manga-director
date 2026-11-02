"""Human-confirmed reuse of an older shot must not rewrite its generation history."""
import copy
import unittest
import test_production_coverage as fixture
from backend.workflow import WorkflowError


class ShotReselectionTests(unittest.TestCase):
    setUp = fixture.CoverageTests.setUp
    begin = fixture.CoverageTests.begin
    finish = fixture.CoverageTests.finish
    image = fixture.CoverageTests.image
    save_entities = fixture.CoverageTests.save_entities
    complete = fixture.CoverageTests.complete

    def revise(self, entity_id):
        plan = self.workflow.get_plan(self.ctx, self.project['id'])
        keys = {'id','category','name','description','origin','quote','scriptId','variant'}
        rows = [{k:v for k,v in e.items() if k in keys} for e in plan['entities']]
        next(e for e in rows if e['id']==entity_id)['description'] += ' 调整构图要求'
        self.workflow.save_plan(self.ctx,self.project['id'],{'expectedVersion':plan['version'],'stylePrompt':plan['stylePrompt'],'entities':rows})

    def setup_old_shot(self):
        self.complete()
        asset=next(a for a in self.workflow.list_assets(self.ctx,self.project['id'])['items'] if a['category']=='shot')
        r=asset['revisions'][0]
        self.revise(r['entityId'])
        return r

    def select(self,r,**extra):
        asset=next(a for a in self.workflow.list_assets(self.ctx,self.project['id'])['items'] if a['id']==r['assetId'])
        return self.workflow.review(self.ctx,asset['id'],{'revisionId':r['id'],'sha256':r['sha256'],'decision':'approved',
            'expectedVersion':asset['version'],'note':'人工确认此旧版画面仍适用于当前镜头',**extra})['revision']

    def test_explicit_reselection_preserves_original_snapshot_and_is_scoped_to_current_plan(self):
        original=self.setup_old_shot()
        old=self.workflow.get_revision(self.ctx,original['id'],require_approved=False)
        self.assertEqual(old['status'],'stale')
        self.assertEqual(old['reconfirmation']['entityVersion'],2)
        with self.assertRaises(WorkflowError): self.select(old)
        with self.assertRaises(WorkflowError): self.select(old,confirmCurrentBasis=True,expectedEntityVersion=1)
        chosen=self.select(old,confirmCurrentBasis=True,expectedEntityVersion=2)
        self.assertEqual(chosen['status'],'ready')
        self.assertEqual(chosen['applicability']['entityVersion'],2)
        for field in ('entityVersion','sourceRevisionIds','sha256','taskId','prompt'):
            self.assertEqual(chosen[field],original[field])
        self.revise(original['entityId'])
        changed=self.workflow.get_revision(self.ctx,original['id'],require_approved=False)
        self.assertEqual(changed['status'],'stale')
        self.assertEqual(changed['reconfirmation']['entityVersion'],3)

    def test_upstream_change_cannot_be_silently_confirmed_as_compatible(self):
        r=self.setup_old_shot()
        source=self.workflow.get_revision(self.ctx,r['sourceRevisionIds'][0])
        self.revise(source['entityId'])
        old=self.workflow.get_revision(self.ctx,r['id'],require_approved=False)
        self.assertNotIn('reconfirmation',old)
        with self.assertRaises(WorkflowError): self.select(old,confirmCurrentBasis=True,expectedEntityVersion=2)

    def test_asset_identity_changes_and_unknown_invalidation_remain_view_only(self):
        r=self.setup_old_shot()
        with self.workflow.repository.transaction(self.ctx,write=True) as tx:
            tx.state['revisions'][r['id']]['staleReason']='unknown'
        self.assertNotIn('reconfirmation',self.workflow.get_revision(self.ctx,r['id'],require_approved=False))
        source=self.workflow.get_revision(self.ctx,r['sourceRevisionIds'][0])
        self.revise(source['entityId'])
        self.assertNotIn('reconfirmation',self.workflow.get_revision(self.ctx,source['id'],require_approved=False))

    def test_old_shot_can_be_explicit_edit_input_without_adopting_it(self):
        from backend.workflow.image_edit import editing_reference
        r=self.setup_old_shot()
        body={'editRevisionId':r['id'],'editSha256':r['sha256'],'confirmEditReference':True,'editNote':'修正手部'}
        with self.assertRaises(WorkflowError):
            editing_reference(self.workflow,self.ctx,self.project['id'],r['entityId'],self.owner,'image25_storyboard',body)
        before=self.workflow.get_revision(self.ctx,r['id'],require_approved=False)
        seed,refs,_=editing_reference(self.workflow,self.ctx,self.project['id'],r['entityId'],self.owner,'image25_storyboard',
                                     {**body,'expectedEditEntityVersion':2})
        self.assertEqual(self.workflow.get_revision(self.ctx,seed)['sha256'],r['sha256'])
        self.assertEqual(refs,r['sourceRevisionIds'])
        self.assertEqual(before,self.workflow.get_revision(self.ctx,r['id'],require_approved=False))


if __name__=='__main__':unittest.main()
