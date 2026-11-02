"""Art-study lineage through the real workflow store, using synthetic images only."""
import copy
from types import SimpleNamespace
import unittest
import test_workflow as fixture
from backend.workflow import WorkflowError
from backend.workflow.art_studies import prepare, entity_id
from backend.workflow.art_direction import inherited_references


class ArtStudyTests(unittest.TestCase):
    setUp = fixture.WorkflowTests.setUp
    task = fixture.WorkflowTests.task
    output = fixture.WorkflowTests.output
    review = fixture.WorkflowTests.review
    asset = fixture.WorkflowTests.asset

    def connect(self):
        self.calls=[]
        def prepared(ctx, spec, revision, key):
            built=self.workflow.build_spec(ctx,spec,self.owner)
            self.calls.append((built,key))
            return built
        self.workflow.tasks=SimpleNamespace(_selection=lambda ctx:{'revision':4},
            _owner=lambda ctx,s:self.owner,prepare=prepared)

    def study(self,role,samples=None):
        body={'role':role,'prompt':'合成美术试做，不调用任何供应商','expectedSelectionRevision':4,
            'expectedPlanVersion':self.workflow.get_plan(self.ctx,self.project_id)['version'],
            'expectedArtDirectionVersion':(self.workflow.get_project(self.ctx,self.project_id)['artDirection'] or {}).get('version',0),
            'idempotencyKey':'study-'+role,**({'samples':samples} if samples is not None else {})}
        spec=prepare(self.workflow,self.ctx,self.project_id,body)
        return self.review(self.workflow.record_output(self.ctx,{**spec,'id':'art-'+role,'ownership':self.owner,'status':'downloading'},fixture.png()))

    def refs(self,*revisions):
        return {role:{'revisionId':r['id'],'sha256':r['sha256']} for role,r in zip(('character','scene','trial'),revisions)}

    def confirm(self,samples,version=0):
        return self.workflow.confirm_art_direction(self.ctx,self.project_id,{'samples':samples,
            'notes':'统一细线条与柔和暖色，身份分别固定','expectedVersion':version,'confirmStyle':True})

    def test_three_studies_work_without_production_job_and_pin_real_sources(self):
        self.connect();person=self.study('character');scene=self.study('scene')
        trial=self.study('trial',self.refs(person,scene));before=self.workflow.get_plan(self.ctx,self.project_id)
        d=self.confirm(self.refs(person,scene,trial))
        self.assertTrue(d['valid']);self.assertEqual(set(d['samples']),{'character','scene','trial'})
        self.assertEqual(d['samples']['trial']['sourceRevisionIds'],[person['id'],scene['id']])
        self.assertEqual(d['samples']['trial']['prompt'],trial['prompt'])
        self.assertEqual(self.workflow.get_plan(self.ctx,self.project_id),before)
        self.assertEqual(self.confirm(self.refs(person,scene,trial),1)['version'],1)

    def test_missing_foreign_wrong_category_and_changed_trial_are_rejected(self):
        self.connect();person=self.study('character');scene=self.study('scene')
        with self.assertRaises(WorkflowError):self.study('trial',self.refs(person))
        wrong=self.refs(person,person)
        with self.assertRaises(WorkflowError):self.study('trial',wrong)
        trial=self.study('trial',self.refs(person,scene))
        replacement=self.review(self.output('mj_style',entity='ent_character'))
        with self.assertRaises(WorkflowError):self.confirm(self.refs(replacement,scene,trial))
        with self.assertRaises(WorkflowError):self.confirm(self.refs(person,scene))
        self.owner={**self.owner,'spaceId':'other'}
        with self.assertRaises(WorkflowError):self.confirm(self.refs(person,scene,trial))

    def test_sample_change_invalidates_whole_standard_without_deleting_versions(self):
        self.connect();person=self.study('character');scene=self.study('scene');trial=self.study('trial',self.refs(person,scene))
        self.confirm(self.refs(person,scene,trial))
        self.review(self.output('mj_style',entity=entity_id(self.project_id,'scene'),color=(20,30,40)))
        self.assertFalse(self.workflow.get_project(self.ctx,self.project_id)['artDirection']['valid'])
        self.assertEqual(len(self.asset(scene)['revisions']),2)

    def test_conflict_is_before_prepare_and_other_plan_rows_stay_intact(self):
        self.connect();before=self.workflow.get_plan(self.ctx,self.project_id)
        with self.assertRaises(WorkflowError):prepare(self.workflow,self.ctx,self.project_id,{
            'role':'character','prompt':'合成提示词','expectedSelectionRevision':4,'expectedPlanVersion':-1})
        self.assertFalse(self.calls)
        self.assertEqual(self.workflow.get_plan(self.ctx,self.project_id),before)

    def test_style_references_are_supplemental_and_never_replace_identity(self):
        d={'samples':{'character':{'revisionId':'char-style'},'scene':{'revisionId':'scene-style'}}}
        refs,prompt=inherited_references(d,'character',['identity-master'],'人物乙')
        self.assertEqual(refs,['identity-master','char-style']);self.assertIn('不复制',prompt)
        refs,prompt=inherited_references(d,'shot',['state','space'],'当前镜头')
        self.assertEqual(refs,['state','space','char-style','scene-style'])

    def test_new_exploration_does_not_copy_old_confirmed_prompt_or_version(self):
        self.connect();person=self.study('character');scene=self.study('scene');trial=self.study('trial',self.refs(person,scene))
        self.confirm(self.refs(person,scene,trial))
        spec=prepare(self.workflow,self.ctx,self.project_id,{'role':'character','prompt':'尝试不同画风',
            'expectedSelectionRevision':4,'expectedArtDirectionVersion':1,'idempotencyKey':'new-style'})
        self.assertEqual(spec['workflowSnapshot']['artDirectionVersion'],0)
        self.assertEqual(spec['prompt'],'尝试不同画风')
