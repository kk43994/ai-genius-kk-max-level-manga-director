"""Module route registration only. The shared HTTP server remains integration-owned."""
from dataclasses import dataclass, field as datafield
from .errors import AuthError, field

PUBLIC_ROUTES = frozenset({('GET', '/api/v1/oauth/libtv/callback')})


@dataclass
class Response:
    status: int
    body: dict | bytes
    headers: dict = datafield(default_factory=dict, repr=False)


def register_routes(router, services):
    def provider():
        result = field(services, 'providers')
        if result is None:
            raise AuthError('PROVIDER_UNCONFIGURED')
        return result

    def body(ctx, allowed):
        value = field(ctx, 'json')
        if not isinstance(value, dict) or not set(value) <= set(allowed):
            raise AuthError('VALIDATION_FAILED')
        return value

    def respond(ctx, operation):
        meta = {'requestId': field(ctx, 'requestId', ''), 'apiVersion': 1}
        headers = {'Cache-Control': 'no-store', 'Pragma': 'no-cache', 'Vary': 'Cookie'}
        try:
            return Response(200, {'data': operation(), 'meta': meta}, headers)
        except AuthError as err:
            return Response(err.status, {'error': err.public(), 'meta': meta}, headers)

    def authorize(ctx, params):
        def run():
            value = body(ctx, ('provider', 'returnPath', 'intent', 'purpose', 'hasUnsavedChanges', 'workspaceLabel'))
            owner_purpose = value.get('purpose') in ('bind_owner', 'recover_workspace') or value.get('intent') in ('bind_owner', 'recover')
            if value.get('provider', 'libtv' if owner_purpose else None) != 'libtv':
                raise AuthError('VALIDATION_FAILED')
            return provider().begin_authorization(ctx, returnPath=value.get('returnPath', '/'),
                intent=value.get('intent', 'connect'), purpose=value.get('purpose'),
                hasUnsavedChanges=value.get('hasUnsavedChanges'),
                workspaceLabel=value.get('workspaceLabel', '我的工作区'))
        return respond(ctx, run)

    def reauthorize(ctx, params):
        def run():
            value = body(ctx, ('expectedVersion', 'returnPath'))
            return provider().begin_authorization(ctx, providerAccountId=params['id'],
                expectedVersion=value.get('expectedVersion'), returnPath=value.get('returnPath', '/'))
        return respond(ctx, run)

    def remove(ctx, params):
        def run():
            value = body(ctx, ('expectedVersion',))
            return provider().remove_account(ctx, params['id'], value.get('expectedVersion'))
        return respond(ctx, run)

    def cancel(ctx, params):
        def run():
            body(ctx, ())
            return provider().cancel_authorization(ctx, params['id'])
        return respond(ctx, run)

    def callback(ctx, params):
        try:
            result = provider().complete_authorization(ctx, field(ctx, 'query', {}))
            return Response(**result)
        except AuthError:
            # Callback errors are not reflected into HTML, logs or a query string.
            return Response(303, b'', {'Location': '/?authorizationStatus=failed',
                'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
                'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'"})

    router.add('GET', '/api/v1/provider-accounts',
               lambda ctx, params: respond(ctx, lambda: provider().list_accounts(ctx)))
    router.add('GET', '/api/v1/provider-accounts/{id}',
               lambda ctx, params: respond(ctx, lambda: provider().get_account(ctx, params['id'])))
    router.add('POST', '/api/v1/provider-accounts/authorize', authorize)
    router.add('POST', '/api/v1/provider-accounts/{id}/reauthorize', reauthorize)
    router.add('DELETE', '/api/v1/provider-accounts/{id}', remove)
    router.add('GET', '/api/v1/authorization-attempts/{id}',
               lambda ctx, params: respond(ctx, lambda: provider().get_attempt(ctx, params['id'])))
    router.add('POST', '/api/v1/authorization-attempts/{id}/cancel', cancel)
    router.add('GET', '/api/v1/oauth/libtv/callback', callback)
