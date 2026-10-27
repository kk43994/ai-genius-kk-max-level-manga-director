from .errors import AuthError, ProviderWorkerContext


def __getattr__(name):
    if name == 'ProviderService':
        from .service import ProviderService
        return ProviderService
    if name in ('PUBLIC_ROUTES', 'Response', 'register_routes'):
        from . import routes
        return getattr(routes, name)
    raise AttributeError(name)

__all__ = ['AuthError', 'ProviderWorkerContext', 'ProviderService', 'PUBLIC_ROUTES', 'Response', 'register_routes']
