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


def make_adapter(services,task_repository):
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

    return GenerationAdapter(journal=StoreGenerationJournal(services.storage,original_context),
        submission_bridge=TaskSubmissionBridge(task_repository,original_context),
        project_resolver=OfficialProjectResolver(saved_project_candidate),
        references=WorkflowReferences(),media_transfer=SafeMediaTransfer(allowed_hosts=(),evidence=''),
        recipes={},responses=ResponseContracts(),reference_route=ReferenceNodeRoute(),policy=GenerationPolicy())


def release_gates(adapter):
    from backend.generation import GenerationAdapter
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
