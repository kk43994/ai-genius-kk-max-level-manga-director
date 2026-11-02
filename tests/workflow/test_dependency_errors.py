"""Production routes preserve typed, safe dependency failures before preparation."""
from types import SimpleNamespace
import unittest
from backend.workflow.routes import register_routes
from backend.auth.errors import AuthError
from backend.spaces.errors import SpaceError
from backend.tasks.errors import TaskError


class DependencyErrors(unittest.TestCase):
    def test_image_prepare_surfaces_account_and_reference_failures(self):
        routes={}
        router=SimpleNamespace(add=lambda method,path,handler:routes.update({(method,path):handler}))
        pending=[]
        def prepare(*args):raise pending[0]
        workflow=SimpleNamespace(production=SimpleNamespace(prepare_image=prepare))
        register_routes(router,{'workflow':workflow})
        for error in (AuthError('PROVIDER_ACCOUNT_READ_UNAVAILABLE'),
                      SpaceError('PROVIDER_ACCOUNT_READ_UNAVAILABLE','账号暂不可读',retryable=True),
                      TaskError('SOURCE_REVIEW_REQUIRED','请先审核参考')):
            pending[:]=[error]
            response=routes[('POST','/api/v1/production-jobs/{productionId}/images/prepare')](
                SimpleNamespace(tenantId='synthetic',csrfVerified=True,json={}),{'productionId':'synthetic'})
            self.assertEqual(response.status,error.status)
            self.assertEqual(response.body['error']['code'],error.code)
