"""Actual composition, shared Store/context and controlled protocol-gap errors."""
import unittest
from backend.app import RequestContext
from backend.generation import GenerationAdapter,GenerationError
from backend.integration_generation import request_scope
from backend.tasks.errors import provider_failure
import test_composed_http as composed


class GenerationCompositionTests(unittest.TestCase):
    setUp=composed.ComposedHTTPTests.setUp
    close=composed.ComposedHTTPTests.close
    start=composed.ComposedHTTPTests.start
    request=composed.ComposedHTTPTests.request
    session=composed.ComposedHTTPTests.session

    def test_real_adapter_is_injected_with_shared_repository_and_runtime_catalog(self):
        adapter=self.app.services.generation
        self.assertIsInstance(adapter,GenerationAdapter)
        self.assertIs(self.app.services.providers.operation_adapter,adapter)
        self.assertIs(adapter.journal.store,self.app.services.storage)
        self.assertIs(adapter.bridge.repository,self.app.services.tasks.repository)
        self.assertEqual(adapter.catalog.tool('generation_submit')['name'],'generation_submit')
        report=self.request('/ready')[2]['data']['generation']
        self.assertTrue(report['adapterInstalled']);self.assertTrue(report['requestScopeBound'])
        self.assertEqual(set(report['gates']),{'productionProtocolMapping','creatorAuthorization','publicOAuthCallback','paidRealRun'})
        self.assertTrue(all(gate['ready'] is False for gate in report['gates'].values()))
        self.assertEqual(adapter.recipes,{})

    def test_journal_requires_active_request_context_and_cannot_use_another_tenant(self):
        _,data=self.session();_,other=self.session()
        owner={'tenantId':data['tenant']['id'],'provider':'libtv','providerAccountId':'synthetic-account',
            'providerIssuer':'https://mcp.liblib.tv/','providerSubject':'synthetic-subject','spaceId':'synthetic-space','spaceKind':'personal'}
        journal=self.app.services.generation.journal
        with self.assertRaises(GenerationError):
            with journal.edit(owner,'synthetic-task'):pass
        ctx=RequestContext('synthetic-request','POST','/api/v1/tasks/prepare',tenantId=data['tenant']['id'],siteSessionId=data['session']['id'])
        with request_scope(ctx):
            with journal.edit(owner,'synthetic-task') as state:state['testValue']='retained-in-original'
        ctx.tenantId=other['tenant']['id'];ctx.siteSessionId=other['session']['id']
        with request_scope(ctx),self.assertRaises(GenerationError):
            with journal.edit(owner,'synthetic-task'):pass
        ctx.tenantId=data['tenant']['id'];ctx.siteSessionId=data['session']['id']
        with request_scope(ctx),journal.edit(owner,'synthetic-task') as state:
            self.assertEqual(state['testValue'],'retained-in-original')

    def test_scope_and_mapping_gaps_keep_fixed_codes_without_raw_provider_text(self):
        for code in ('PROVIDER_SCOPE_REQUIRED','PROVIDER_SCOPE_UNAVAILABLE','MODEL_BINDING_REQUIRED',
                     'PROJECT_BINDING_REQUIRED','PROVIDER_RESPONSE_CONTRACT_REQUIRED','TRANSFER_HOST_UNVERIFIED'):
            error=Exception('synthetic-private-upstream-url');error.code=code
            status,public=provider_failure(error)
            self.assertEqual(status,'needs_attention');self.assertEqual(public['code'],code)
            self.assertNotIn('private',str(public));self.assertFalse(public['details']['submissionAttempted'])
            self.assertTrue(provider_failure(error,attempted=True)[1]['details']['submissionAttempted'])
