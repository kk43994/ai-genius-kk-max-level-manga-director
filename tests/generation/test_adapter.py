import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.generation import GenerationError, GenerationPolicy, ResponseContracts, ToolCatalog
from backend.generation.projects import OfficialProjectResolver
from backend.generation.journal import StoreGenerationJournal
from backend.generation.types import AuthorizedMCP, ProjectBinding
from helpers import Fixture


class AdapterTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / 'work' / 'generation-tests'
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.f = Fixture(self.temp.name)
        for name in ['socket.create_connection', 'socket.getaddrinfo']:
            guard = patch(name, side_effect=AssertionError('LIVE NETWORK FORBIDDEN IN TESTS'))
            guard.start()
            self.addCleanup(guard.stop)

    def error(self, code, operation):
        with self.assertRaises(GenerationError) as cm:
            operation()
        self.assertEqual(cm.exception.code, code)
        return cm.exception

    def ready(self, **kwargs):
        self.f.prepare(**kwargs)
        self.f.confirm()

    def test_image2_can_read_approved_master_asset_bytes_for_state_generation(self):
        payload = self.f.payload(recipe='image2_asset', with_reference=True)
        self.f.refs['revision_one'] = replace(self.f.refs['revision_one'], stage='asset')
        prepared = self.f.client.prepare(payload)
        self.assertEqual(prepared['count'], 1)
        self.assertEqual(self.f.count('generation_submit'), 0)
        self.assertEqual(self.f.media.puts, [])
        self.f.refs['revision_one'] = replace(self.f.refs['revision_one'], approved=False)
        self.error('SOURCE_CHANGED', lambda: self.f.client.prepare({**payload, 'localTaskId':'new-task'}))

    def test_prepare_has_only_read_tools_and_unknown_cost(self):
        result = self.f.prepare()
        self.assertEqual(result['cost']['state'], 'unknown')
        self.assertEqual(result['count'], 1)
        self.assertEqual([name for name, _ in self.f.transport.calls], ['get_model'])
        self.assertEqual(self.f.media.puts, [])
        self.assertEqual(self.f.state()['steps'], {})

    def test_read_catalogue_and_exact_model(self):
        self.assertEqual(self.f.client.list_models(), {'catalogue': ['synthetic-image-v1']})
        self.assertIn('inputContract', self.f.client.get_model('synthetic-image-v1'))
        self.error('INPUT_INVALID', lambda: self.f.client.get_model(' model '))

    def test_read_scope_missing_makes_no_calls(self):
        self.f.scopes = frozenset({'libtv:account:read'})
        self.error('PROVIDER_SCOPE_REQUIRED', self.f.prepare)
        self.assertEqual(self.f.transport.calls, [])

    def test_auth_revoked_and_wrong_owner_fail_closed(self):
        self.f.client._authorize = lambda _: AuthorizedMCP({**self.f.owner, 'providerSubject': 'other'}, self.f.scopes, self.f.transport)
        self.error('OWNERSHIP_MISMATCH', self.f.prepare)
        self.assertEqual(self.f.transport.calls, [])

    def test_original_owner_is_a_copy_and_space_cannot_be_overridden(self):
        self.f.owner['spaceId'] = 'switched_space'
        self.error('OWNERSHIP_MISMATCH', self.f.prepare)
        self.error('OWNERSHIP_MISMATCH', lambda: self.f.client.list_models('different_space'))

    def test_default_policy_blocks_external_writes(self):
        self.ready()
        self.f.adapter.policy = GenerationPolicy()
        self.error('GENERATION_DISABLED', self.f.submit)
        self.assertEqual(self.f.count('generation_submit'), 0)

    def test_submit_requires_persisted_user_confirmation(self):
        self.f.prepare()
        self.error('CONFIRMATION_REQUIRED', self.f.submit)
        self.assertEqual(self.f.count('generation_submit'), 0)

    def test_changed_spec_or_key_never_charges(self):
        self.ready()
        self.f.submission['spec'] = {**self.f.spec, 'prompt': 'changed'}
        self.error('IDEMPOTENCY_CONFLICT', self.f.submit)
        self.f.submission['spec'] = self.f.spec
        self.error('CONFIRMATION_REQUIRED', lambda: self.f.client.submit(self.f.submission, 'different_key'))
        self.assertEqual(self.f.count('generation_submit'), 0)

    def test_model_schema_drift_blocks_submit(self):
        self.ready()
        self.f.transport.model_schema['inputContract']['parameterSchemas']['count']['maximum'] = 3
        self.error('SOURCE_CHANGED', self.f.submit)
        self.assertEqual(self.f.count('generation_submit'), 0)

    def test_count_bounds_types_and_model_params(self):
        for settings in [{'count': 0}, {'count': 5}, {'count': True}, {'aspect': '9:99'}, {'invented': 5}, {'strength': 2}, {'model': 'x'}, {'settings': {'imageList': []}}]:
            with self.subTest(settings=settings):
                self.error('INPUT_INVALID', lambda: self.f.client.prepare(self.f.payload(settings=settings)))

    def test_unverified_model_shape_and_unconfigured_recipe(self):
        self.f.transport.model_schema = {'models': []}
        self.error('MODEL_CONTRACT_UNVERIFIED', self.f.prepare)
        self.f.adapter.recipes = {}
        self.error('MODEL_BINDING_REQUIRED', self.f.prepare)

    def test_video_and_audio_are_disabled(self):
        for recipe in ['video', 'audio', 'script_analysis']:
            self.error('VIDEO_OR_AUDIO_DISABLED', lambda: self.f.client.prepare(self.f.payload(recipe=recipe)))

    def test_submit_once_and_receipt_persisted(self):
        self.ready(settings={'count': 2})
        first = self.f.submit()
        self.assertEqual(first['status'], 'queued')
        self.assertEqual(self.f.submit(), first)
        self.assertEqual(self.f.count('generation_submit'), 1)
        with self.f.repository.transaction(self.f.ctx) as tx:
            self.assertEqual(tx.get_task('task_synthetic')['providerReceipt']['taskId'], 'provider_task')

    def test_timeout_survives_store_reopen_and_never_resubmits(self):
        self.ready()
        self.f.transport.failures['generation_submit'] = TimeoutError('SECRET signed URL upstream')
        exc = self.error('PROVIDER_UNAVAILABLE', self.f.submit)
        self.assertNotIn('SECRET', str(exc))
        self.assertEqual(exc.provider_receipt, {'projectId': 'remote_project'})
        from backend.storage import Store
        reopened = Store(self.f.root / 'data', encryption_key=b'G' * 32, release_root=self.f.root / 'release-next')
        self.f.adapter.journal = StoreGenerationJournal(reopened, self.f.ctx)
        self.f.client = self.f.adapter.bind(ownership=self.f.owner, authorize=self.f.authorize)
        self.f.transport.failures.clear()
        self.error('OPERATION_UNKNOWN', self.f.submit)
        self.error('ORIGINAL_RECEIPT_REQUIRED', lambda: self.f.client.lookup(exc.provider_receipt))
        self.assertEqual(self.f.count('generation_submit'), 1)

    def test_canvas_receipt_cannot_become_task(self):
        self.ready()
        self.f.transport.overrides['generation_submit'] = {'task_id': 'cop_canvas'}
        self.error('PROVIDER_PROTOCOL_ERROR', self.f.submit)
        self.assertEqual(self.f.count('generation_submit'), 1)

    def test_reference_prepare_never_uploads_or_creates_nodes(self):
        self.f.prepare(recipe='image2_asset', with_reference=True)
        self.assertEqual([name for name, _ in self.f.transport.calls], ['get_model'])

    def test_missing_response_mapping_stops_before_any_reference_write(self):
        self.f.adapter.responses = ResponseContracts()
        self.error('PROVIDER_RESPONSE_CONTRACT_REQUIRED', lambda: self.f.prepare(recipe='image2_asset', with_reference=True))
        self.assertEqual(self.f.transport.calls, [])

    def test_synthetic_mapping_cannot_run_under_production_policy(self):
        self.f.adapter.policy = GenerationPolicy(allow_external_writes=True)
        self.error('PROVIDER_RESPONSE_CONTRACT_REQUIRED', lambda: self.f.prepare(recipe='image2_asset', with_reference=True))

    def test_unapproved_cross_owner_and_hash_changed_sources(self):
        for change in ['review', 'owner', 'bytes']:
            p = self.f.payload(recipe='image2_asset', with_reference=True)
            if change == 'review':
                p['sources'][0]['review'] = 'pending'
            elif change == 'owner':
                p['sources'][0]['ownership'] = {**self.f.owner, 'providerIssuer': 'https://other.invalid/'}
            else:
                self.f.refs['revision_one'] = replace(self.f.refs['revision_one'], content=b'changed')
            self.error('OUTPUT_INVALID' if change == 'bytes' else 'SOURCE_REVIEW_REQUIRED', lambda: self.f.client.prepare(p))

    def test_nano_refine_only_uses_original_image2(self):
        p = self.f.payload(recipe='nano_refine', with_reference=True)
        self.f.refs['revision_one'] = replace(self.f.refs['revision_one'], stage='refine')
        self.error('SOURCE_CHANGED', lambda: self.f.client.prepare(p))

    def test_reference_upload_node_and_charged_run_sequence(self):
        self.ready(recipe='image2_asset', with_reference=True)
        result = self.f.submit()
        names = [n for n, _ in self.f.transport.calls]
        self.assertLess(names.index('upload_complete'), names.index('create_node'))
        self.assertLess(names.index('read_node'), names.index('update_node'))
        create = next(a for n, a in self.f.transport.calls if n == 'create_node')
        run = next(a for n, a in self.f.transport.calls if n == 'update_node')
        self.assertFalse(create['run'])
        self.assertTrue(run['run'])
        self.assertEqual(run['leftEnsure'], ['reference_node'])
        self.assertEqual(run['params']['count'], 1)
        self.assertNotIn('imageList', run['params'])
        self.assertEqual(result['providerReceipt']['nodeId'], 'image_node')
        self.assertNotIn('test-signature', json.dumps(self.f.state()))

    def test_reference_timeout_recovers_original_node_without_paid_retry(self):
        self.ready(recipe='nano_refine', with_reference=True)
        self.f.transport.failures['update_node'] = TimeoutError('upstream secret')
        exc = self.error('PROVIDER_UNAVAILABLE', self.f.submit)
        self.assertEqual(exc.provider_receipt['nodeId'], 'image_node')
        self.f.transport.nodes['image_node']['taskId'] = 'provider_task'
        self.f.transport.nodes['image_node']['taskRequestKey'] = 'generation_task_synthetic'
        self.f.transport.failures.clear()
        result = self.f.client.lookup(exc.provider_receipt)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.f.count('update_node'), 1)

    def test_reference_review_change_during_upload_blocks_paid_step(self):
        self.ready(recipe='image2_asset', with_reference=True)
        def mutate(name, args):
            if name == 'upload_media':
                self.f.refs['revision_one'] = replace(self.f.refs['revision_one'], approved=False)
        self.f.transport.hook = mutate
        self.error('SOURCE_CHANGED', self.f.submit)
        self.assertEqual(self.f.count('update_node'), 0)

    def test_upload_timeout_and_review_pending_stop_before_generation(self):
        self.ready(recipe='image2_asset', with_reference=True)
        self.f.transport.overrides['upload_media'] = {'projectId': 'remote_project', 'status': 'review_pending'}
        self.error('UPLOAD_UNCONFIRMED', self.f.submit)
        self.error('OPERATION_UNKNOWN', self.f.submit)
        self.assertEqual(self.f.count('upload_ticket'), 1)
        self.assertEqual(self.f.count('update_node'), 0)

    def test_missing_write_scope_prevents_upload(self):
        self.ready(recipe='image2_asset', with_reference=True)
        self.f.scopes = frozenset({'libtv:project:read', 'libtv:task:write'})
        self.error('PROVIDER_SCOPE_REQUIRED', self.f.submit)
        self.assertEqual(self.f.count('upload_ticket'), 0)

    def test_query_wrong_task_or_project_rejected(self):
        self.ready()
        receipt = self.f.submit()['providerReceipt']
        for field in ['taskId', 'projectId']:
            self.f.transport.overrides['task_status'] = {'projectId': 'remote_project', 'taskId': 'provider_task',
                                                        'nodeId': 'image_node', 'status': 'completed', field: 'foreign'}
            self.error('PROVIDER_RECEIPT_MISMATCH', lambda: self.f.client.lookup(receipt))

    def test_task_failed_and_unknown_states_not_completed(self):
        self.ready()
        receipt = self.f.submit()['providerReceipt']
        for state, expected in [('failed', 'failed'), ('new_status', 'unknown')]:
            self.f.transport.overrides['task_status'] = {'projectId': 'remote_project', 'taskId': 'provider_task',
                                                        'nodeId': None, 'status': state}
            self.assertEqual(self.f.client.lookup(receipt)['status'], expected)

    def test_safe_download_count_and_resume_original_delivery(self):
        self.ready(settings={'count': 2})
        receipt = self.f.client.lookup(self.f.submit()['providerReceipt'])['providerReceipt']
        downloaded = self.f.client.download(receipt)
        self.assertEqual(len(downloaded), 2)
        self.assertEqual(downloaded[0].content, self.f.raw)
        self.f.client.download(receipt)
        self.assertEqual(self.f.count('prepare_project_delivery'), 2)
        self.assertEqual(self.f.count('get_web_operation_status'), 2)
        self.assertNotIn('test-signature', json.dumps(self.f.state()))

    def test_delivery_timeout_is_never_automatically_resent(self):
        self.ready()
        receipt = self.f.client.lookup(self.f.submit()['providerReceipt'])['providerReceipt']
        self.f.transport.failures['prepare_project_delivery'] = TimeoutError()
        self.error('PROVIDER_UNAVAILABLE', lambda: self.f.client.download(receipt))
        self.f.transport.failures.clear()
        self.error('OPERATION_UNKNOWN', lambda: self.f.client.download(receipt))
        self.assertEqual(self.f.count('prepare_project_delivery'), 1)

    def test_download_checks_image_bytes_even_for_injected_transfer(self):
        self.ready()
        receipt = self.f.submit()['providerReceipt']
        self.f.media.raw = b'<html>failure</html>'
        self.error('OUTPUT_INVALID', lambda: self.f.client.download(receipt))

    def test_project_mapping_requires_live_same_space_evidence(self):
        self.f.adapter.projects = OfficialProjectResolver(lambda owner, project: ProjectBinding('remote_project', owner, '', False))
        self.f.prepare()
        self.assertEqual(self.f.count('project_info'), 1)
        self.f.transport.overrides['project_info'] = {'projectId': 'remote_project', 'spaceId': 'other_space', 'spaceKind': 'personal'}
        self.error('OWNERSHIP_MISMATCH', self.f.prepare)

    def test_mcp_error_text_and_remote_schema_refs_are_not_used(self):
        c = ToolCatalog.bundled()
        self.error('PROVIDER_PROTOCOL_ERROR', lambda: c.response('get_model', {'isError': True, 'content': [{'type': 'text', 'text': 'SECRET'}]}))
        from backend.generation.contracts import validate
        self.error('PROVIDER_PROTOCOL_ERROR', lambda: validate({'$ref': 'https://private.invalid/schema'}, {}))
        self.assertEqual(c.response('get_model', {'content': [{'type': 'text', 'text': '{"ok":true}'}]}), {'ok': True})

    def test_missing_recovery_contract_cannot_start_paid_task(self):
        self.ready()
        del self.f.adapter.responses._items['task_status']
        self.error('PROVIDER_RESPONSE_CONTRACT_REQUIRED', self.f.submit)
        self.assertEqual(self.f.count('generation_submit'), 0)

    def test_delivery_wrong_node_is_not_downloaded(self):
        self.ready()
        receipt = self.f.client.lookup(self.f.submit()['providerReceipt'])['providerReceipt']
        self.f.transport.overrides['prepare_project_delivery'] = {
            'operationId': 'wop_' + 'a' * 64, 'projectId': 'remote_project', 'status': 'done',
            'files': [{'url': 'https://media.invalid/foreign', 'mime': 'image/png',
                       'node': 'other_node', 'index': 0, 'sha256': 'a' * 64}]}
        self.error('PROVIDER_RECEIPT_MISMATCH', lambda: self.f.client.download(receipt))
        self.assertEqual(self.f.media.gets, [])

    def test_node_recovery_does_not_adopt_a_later_unrelated_run(self):
        self.ready(recipe='nano_refine', with_reference=True)
        self.f.transport.failures['update_node'] = TimeoutError()
        exc = self.error('PROVIDER_UNAVAILABLE', self.f.submit)
        self.f.transport.nodes['image_node'].update(taskId='provider_task', taskRequestKey='different_run')
        self.f.transport.failures.clear()
        self.error('SUBMISSION_UNKNOWN', lambda: self.f.client.lookup(exc.provider_receipt))
        self.assertEqual(self.f.count('update_node'), 1)


if __name__ == '__main__':
    unittest.main()
