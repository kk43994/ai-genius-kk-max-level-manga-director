import unittest
from pathlib import Path
from types import SimpleNamespace

from backend.tasks.routes import register_routes
from support import Fixture, spec, temporary_directory


class Router:
    def __init__(self):
        self.routes = {}

    def add(self, method, path, handler):
        self.routes[(method, path)] = handler


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.directory = temporary_directory()
        self.addCleanup(self.directory.cleanup)
        self.f = Fixture(Path(self.directory.name) / "routes.sqlite3")
        self.router = Router()
        register_routes(self.router, {"tasks": self.f.service})

    def call(self, method, path, *, json=None, params=None, csrf=True, headers=None):
        ctx = SimpleNamespace(tenantId="tenant_A", csrfVerified=csrf, json=json,
                              headers=headers or {"Idempotency-Key": "route-request-001"}, query={})
        return self.router.routes[(method, path)](ctx, params or {})

    def test_mutation_requires_csrf_and_rejects_client_tenant(self):
        denied = self.call("POST", "/api/v1/tasks/prepare", json={**spec(), "expectedSelectionRevision": 1}, csrf=False)
        self.assertEqual(denied.status, 403)
        denied = self.call("POST", "/api/v1/tasks/prepare", json={**spec(), "expectedSelectionRevision": 1, "tenantId": "tenant_B"})
        self.assertEqual(denied.status, 422)
        self.assertEqual(self.f.providers.submit_count, 0)

    def test_http_shaped_handlers_prepare_read_confirm_and_cancel(self):
        prepared = self.call("POST", "/api/v1/tasks/prepare", json={**spec(), "expectedSelectionRevision": 1})
        self.assertEqual(prepared.status, 200)
        task = prepared.body["data"]["task"]
        got = self.call("GET", "/api/v1/tasks/{taskId}", params={"taskId": task["id"]})
        self.assertEqual(got.body["data"], task)
        confirmed = self.call("POST", "/api/v1/tasks/{taskId}/confirm", params={"taskId": task["id"]}, json={"expectedVersion": task["version"]})
        self.assertEqual(confirmed.status, 200)
        task = confirmed.body["data"]["task"]
        cancelled = self.call("POST", "/api/v1/tasks/{taskId}/cancel", params={"taskId": task["id"]}, json={"expectedVersion": task["version"]})
        self.assertEqual(cancelled.body["data"]["task"]["status"], "cancelled")
        self.assertIn("尚未发起官方生成", cancelled.body["data"]["task"]["error"]["message"])

    def test_unconfigured_task_module_is_not_fake_success(self):
        router = Router()
        register_routes(router, {})
        result = router.routes[("GET", "/api/v1/tasks")](SimpleNamespace(), {})
        self.assertEqual(result.status, 501)

    def test_preparation_dependency_error_does_not_expose_credentials(self):
        def bad_selection(ctx):
            raise RuntimeError("provider token=private-test https://signed.invalid/?signature=secret")
        self.f.selections.get_selection = bad_selection
        result = self.call("POST", "/api/v1/tasks/prepare", json={**spec(), "expectedSelectionRevision": 1})
        self.assertEqual(result.status, 503)
        self.assertNotIn("private-test", str(result.body))
        self.assertNotIn("signed.invalid", str(result.body))

    def test_provider_timeout_before_preparation_has_actionable_safe_message(self):
        def unavailable(ctx):
            error = RuntimeError('token=private-test')
            error.code = 'PROVIDER_UNAVAILABLE'
            raise error
        self.f.selections.get_selection = unavailable
        result = self.call('POST', '/api/v1/tasks/prepare', json={**spec(), 'expectedSelectionRevision':1})
        self.assertEqual(result.status,503)
        self.assertEqual(result.body['error']['code'],'PROVIDER_UNAVAILABLE')
        self.assertIn('不要重复提交生成',result.body['error']['message'])
        self.assertNotIn('尚未提交生成',result.body['error']['message'])
        self.assertNotIn('private-test',str(result.body))
        self.assertEqual(self.f.providers.submit_count,0)

    def test_reference_and_parameter_failures_keep_specific_safe_reason(self):
        from backend.tasks.errors import provider_failure
        for code, expected in [('INPUT_INVALID', '制作参数'), ('SOURCE_CHANGED', '参考图'),
                               ('SOURCE_REVIEW_REQUIRED', '审核参考图')]:
            error = RuntimeError('private-token https://signed.invalid/private')
            error.code = code
            status, public = provider_failure(error)
            self.assertEqual(status, 'needs_attention')
            self.assertEqual(public['code'], code)
            self.assertIn(expected, public['message'])
            self.assertNotIn('private', str(public))

    def test_account_read_outage_preserves_recovery_state_and_safe_error(self):
        from backend.auth.errors import AuthError
        from backend.tasks.errors import provider_failure
        error=AuthError('PROVIDER_ACCOUNT_READ_UNAVAILABLE')
        state, public=provider_failure(error,attempted=True)
        self.assertEqual(state,'needs_attention')
        self.assertEqual(public['code'],error.code)
        self.assertNotIn('generationSubmitted',public['details'])
        self.assertTrue(public['details']['submissionAttempted'])
        def unavailable(ctx):raise error
        self.f.selections.get_selection=unavailable
        result=self.call('POST','/api/v1/tasks/prepare',json={**spec(),'expectedSelectionRevision':1})
        self.assertEqual(result.status,503)
        self.assertEqual(result.body['error']['code'],error.code)
        self.assertEqual(self.f.providers.submit_count,0)


if __name__ == "__main__":
    unittest.main()
