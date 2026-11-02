"""Compose the official adapter with the same Store and request-bound ownership.

No production response fields, model IDs or CDN hosts are guessed here. The
context variable is set only by the HTTP dispatcher after session verification.
There is no worker/admin fallback and no browser-selected tenant context.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_request=ContextVar('asset_lab_generation_request',default=None)


@contextmanager
def request_scope(ctx):
    token=_request.set(ctx)
    try:yield
    finally:_request.reset(token)


def original_context(ownership):
    from backend.storage import TenantContext
    from backend.generation import GenerationError
    ctx=_request.get()
    if ctx is None or not ctx.siteSessionId or ctx.tenantId != ownership.get('tenantId'):
        raise GenerationError('OWNERSHIP_MISMATCH')
    return TenantContext(ctx.tenantId,ctx.siteSessionId,ctx.requestId)


def make_adapter(services,task_repository, *, local_images=False):
    from backend.generation import (GenerationAdapter,GenerationPolicy,OfficialProjectResolver,
        ReferenceNodeRoute,StoreGenerationJournal,TaskSubmissionBridge,WorkflowReferenceReader,
        SafeMediaTransfer,ResponseContracts,ProjectBinding,GenerationError)
    from backend.generation.types import digest,same_owner

    class WorkflowReferences:
        def read(self,ownership,snapshot):
            return WorkflowReferenceReader(services.workflow,original_context).read(ownership,snapshot)

    def saved_project_candidate(ownership,local_project_id):
        ctx=original_context(ownership)
        services.workflow.get_project(ctx,local_project_id)
        identifier='gp_'+digest([ownership['providerAccountId'],ownership['spaceId'],local_project_id])
        try:record=services.storage.get(ctx,'generation.project_bindings',identifier)['data']
        except Exception as error:
            if getattr(error,'code',None)=='NOT_FOUND':raise GenerationError('PROJECT_BINDING_REQUIRED') from None
            raise
        if (record.get('localProjectId')!=local_project_id or not same_owner(record.get('ownership'),ownership)
                or not isinstance(record.get('remoteProjectId'),str) or not record.get('evidence')):
            raise GenerationError('PROJECT_BINDING_REQUIRED')
        # A saved candidate must still pass the live official project/space check.
        return ProjectBinding(record['remoteProjectId'],record['ownership'],record['evidence'])

    if local_images:
        import json
        from pathlib import Path
        from backend.generation.live import LiveGenerationAdapter, PersonalProjects
        from backend.generation.live_reference import LiveReferenceRoute
        from backend.generation.media import PublicMediaResolver
        from backend.generation import RecipeBinding
        from backend.generation.contracts import ToolCatalog
        catalog_path = Path(__file__).parent / 'generation/contracts/libtv-tools-public-2026-10-28.json'
        catalog_data = json.loads(catalog_path.read_text(encoding='utf-8'))
        return LiveGenerationAdapter(journal=StoreGenerationJournal(services.storage,original_context),
            submission_bridge=TaskSubmissionBridge(task_repository,original_context),
            project_resolver=PersonalProjects(services, original_context), references=WorkflowReferences(),
            media_transfer=SafeMediaTransfer(allowed_hosts=('libtv-res.liblib.art','libtv-resource-prod.oss-accelerate.aliyuncs.com'),
                resolver=PublicMediaResolver(('libtv-res.liblib.art','libtv-resource-prod.oss-accelerate.aliyuncs.com')),
                evidence='2026-10-28 official prepare_project_delivery observed permanent media host'),
            recipes={key:RecipeBinding(model, evidence=('2026-11-02 Image2.5 configuration; exact live get_model contract required before preparation'
                if key.startswith('image25_') else '2026-10-28 official search_models and get_model'))
                for key,model in [('mj_style','mj-v8.1'),('image2_asset','lib-image-2'),('storyboard_image','lib-image-2'),
                                  ('image25_style','lib-image-2.5-s'),('image25_asset','lib-image-2.5-s'),
                                  ('image25_storyboard','lib-image-2.5-s'),('nano_refine','nebula-2.1')]},
            catalog=ToolCatalog(catalog_data['tools'], evidence=catalog_data['source']),
            reference_route=LiveReferenceRoute(),
            policy=GenerationPolicy(allow_external_writes=True))

    return GenerationAdapter(journal=StoreGenerationJournal(services.storage,original_context),
        submission_bridge=TaskSubmissionBridge(task_repository,original_context),
        project_resolver=OfficialProjectResolver(saved_project_candidate),
        references=WorkflowReferences(),media_transfer=SafeMediaTransfer(allowed_hosts=(),evidence=''),
        recipes={},responses=ResponseContracts(),reference_route=ReferenceNodeRoute(),policy=GenerationPolicy())


def release_gates(adapter):
    from backend.generation import GenerationAdapter
    from backend.generation.live import LiveGenerationAdapter
    if isinstance(adapter, LiveGenerationAdapter):
        # Configuration is not an acceptance claim or proof of the caller's
        # grant. Every operation still checks the live, original account.
        return {
            'mode':'local_image_preview', 'adapterInstalled':True, 'requestScopeBound':True,
            'creatorScopeVerified':False, 'authorizationCheck':'per_request_live_original_account',
            'paidRunVerified':False, 'paidSubmissionEnabled':adapter.policy.allow_external_writes,
            'reason':'local_full_workflow_acceptance_pending',
            'evidence':'backend/generation/LOCAL_REAL_RUN_2026-10-28.md',
            'missingProductionEvidence':['reference_generation_task_receipt',
                'pending_and_failed_task_status_mapping','full_reviewed_workflow_delivery'],
            'gates':{
                'productionProtocolMapping':{'ready':False,'reason':'reference_run_and_nonterminal_status_acceptance_pending'},
                'creatorAuthorization':{'ready':False,'reason':'checked_per_authenticated_operation',
                    'requiredScopes':['libtv:account:read','libtv:project:read','libtv:project:write',
                        'libtv:media:write','libtv:task:write','libtv:export:write']},
                'publicOAuthCallback':{'ready':False,'reason':'separate_local_instance_only'},
                'paidRealRun':{'ready':False,'reason':'mj_completed_full_workflow_pending'},
            },
        }
    installed=isinstance(adapter,GenerationAdapter)
    return {
        'adapterInstalled':installed,'requestScopeBound':installed,'creatorScopeVerified':False,
        'paidRunVerified':False,'paidSubmissionEnabled':False,
        'reason':'production_protocol_configuration_missing' if installed else 'adapter_not_installed',
        'missingProductionEvidence':['model_bindings_and_input_contract','project_to_space_response_mapping',
            'upload_ticket_and_complete_response_mapping','canvas_node_response_mapping',
            'task_status_response_mapping','delivery_operation_response_mapping','verified_media_hosts_and_headers'],
        'gates':{
            'productionProtocolMapping':{'ready':False,'reason':'response_consumers_and_verified_configuration_incomplete'},
            'creatorAuthorization':{'ready':False,'observedExternalGrant':['libtv:account:read'],
                'requiredAdditionalScopes':['libtv:project:read','libtv:project:write','libtv:media:write','libtv:task:write','libtv:export:write']},
            'publicOAuthCallback':{'ready':False,'reason':'candidate_dcr_invalid_redirect_uri'},
            'paidRealRun':{'ready':False,'reason':'not_authorized_or_executed'},
        },
    }
