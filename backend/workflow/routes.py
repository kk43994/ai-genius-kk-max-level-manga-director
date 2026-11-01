"""Framework-free route registration; the shared adapter owns auth/CSRF/envelopes."""
from dataclasses import dataclass, field

from .errors import WorkflowError, tenant, value


@dataclass
class Response:
    status: int = 200
    body: object = None
    headers: dict = field(default_factory=dict)


def register_routes(router, services):
    workflow = value(services, 'workflow')
    if workflow is None:
        raise RuntimeError('WorkflowService must be composed before route registration')

    def add(method, path, action, binary=False):
        def handler(ctx, params):
            try:
                tenant(ctx)
                if method not in ('GET', 'HEAD') and value(ctx, 'csrfVerified', False) is not True:
                    raise WorkflowError('CSRF_FAILED', '页面验证已失效，请刷新后再试。', 403)
                result = action(ctx, params, value(ctx, 'json', {}) or {}, value(ctx, 'query', {}) or {})
                return result if isinstance(result, Response) else Response(200, result)
            except Exception as error:
                if isinstance(error, WorkflowError) or type(error).__module__ == 'backend.storage.errors':
                    return Response(error.status, {'error': error.public()})
                raise
        router.add(method, '/api/v1' + path, handler)

    add('GET', '/workflow/capabilities', lambda c, p, b, q: workflow.capabilities())
    from .quickstart import start, analyze
    add('POST', '/workflow/start', lambda c, p, b, q: start(workflow, c, b))
    add('POST', '/projects/{projectId}/scripts/{scriptId}/analyze', lambda c, p, b, q:
        analyze(workflow, c, p['projectId'], p['scriptId'], b))
    if getattr(workflow, 'analysis', None):
        ai = workflow.analysis
        add('GET', '/projects/{projectId}/scripts/{scriptId}/analysis', lambda c, p, b, q:
            ai.latest(c, p['projectId'], p['scriptId']))
        add('GET', '/analyses/{analysisId}', lambda c, p, b, q: ai.get(c, p['analysisId']))
        add('POST', '/analyses/{analysisId}/refresh', lambda c, p, b, q: ai.refresh(c, p['analysisId']))
        add('GET', '/analyses/{analysisId}/plan', lambda c, p, b, q: ai.candidate(c, p['analysisId']))
    add('GET', '/projects', lambda c, p, b, q: workflow.list_projects(c))
    add('POST', '/projects', lambda c, p, b, q: workflow.create_project(c, b))
    add('GET', '/projects/{projectId}', lambda c, p, b, q: workflow.get_project(c, p['projectId']))
    add('PATCH', '/projects/{projectId}', lambda c, p, b, q: workflow.update_project(c, p['projectId'], b))
    add('POST', '/projects/{projectId}/scripts', lambda c, p, b, q: workflow.import_script(c, p['projectId'], b))
    add('GET', '/projects/{projectId}/scripts/{scriptId}', lambda c, p, b, q: workflow.get_script(c, p['projectId'], p['scriptId']))
    add('GET', '/projects/{projectId}/plan', lambda c, p, b, q: workflow.get_plan(c, p['projectId']))
    add('PUT', '/projects/{projectId}/plan', lambda c, p, b, q: workflow.save_plan(c, p['projectId'], b))
    add('GET', '/projects/{projectId}/assets', lambda c, p, b, q: workflow.list_assets(c, p['projectId']))
    add('POST', '/assets/{assetId}/reviews', lambda c, p, b, q: workflow.review(c, p['assetId'], b))

    def content(c, p, b, q, thumbnail=False):
        raw, mime = workflow.content(c, p['assetId'], q.get('revisionId'), thumbnail=thumbnail)
        return Response(200, raw, {'Content-Type': mime, 'Cache-Control': 'private, no-store',
                                  'X-Content-Type-Options': 'nosniff', 'Content-Security-Policy': "default-src 'none'"})

    add('GET', '/assets/{assetId}/content', content)
    add('GET', '/assets/{assetId}/thumbnail', lambda c, p, b, q: content(c, p, b, q, True))

    def download(raw, filename):
        return Response(200, raw, {'Content-Type': 'application/zip', 'Cache-Control': 'private, no-store',
                                  'Content-Disposition': f'attachment; filename="{filename}"',
                                  'X-Content-Type-Options': 'nosniff'})

    add('GET', '/projects/{projectId}/export', lambda c, p, b, q:
        download(workflow.export(c, p['projectId'])[0], 'approved-assets.zip'))
    add('GET', '/projects/{projectId}/bundles', lambda c, p, b, q: workflow.list_bundles(c, p['projectId']))
    add('POST', '/projects/{projectId}/bundles', lambda c, p, b, q: workflow.archive(c, p['projectId'], b))
    add('GET', '/projects/{projectId}/bundles/{bundleId}/content', lambda c, p, b, q:
        download(workflow.bundle_content(c, p['projectId'], p['bundleId']), 'archived-assets.zip'))
