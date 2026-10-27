"""Explicit creation of an anonymous session after a lost/expired Cookie.

This public operation grants no existing workspace access. Exact Origin, a
non-simple custom header, and an explicit JSON action prevent cross-site reset.
An active Cookie is never replaced here. Owner recovery still requires OAuth.
"""
from backend.sessions import Response
from backend.storage import StorageError


ANONYMOUS_PATH='/api/v1/session/anonymous'


def register_routes(router,services):
    def anonymous(ctx,params):
        if ctx.origin != services.config.public_origin or ctx.headers.get('X-Asset-Lab-Action') != 'new-anonymous-workspace':
            raise StorageError('ORIGIN_FAILED','请从本站明确建立临时工作区',403)
        if ctx.json != {'confirmNewWorkspace':True}:
            raise StorageError('VALIDATION_FAILED','需要明确确认建立新的空白工作区',422)
        sessions=services.sessions
        try:
            token=sessions.token_from_cookie(ctx.headers.get('Cookie'))
            if token is not None:
                sessions.restore(token,touch=False)
                raise StorageError('SESSION_STILL_ACTIVE','当前会话仍有效，请继续使用当前工作区',409)
        except StorageError as error:
            if error.code != 'SESSION_REQUIRED':raise
        result=sessions.create(request_id=ctx.requestId)
        return Response(200,{'data':result.data}, {'Set-Cookie':result.set_cookie,'Cache-Control':'no-store','Vary':'Cookie'})
    router.add('POST',ANONYMOUS_PATH,anonymous,public=True)
