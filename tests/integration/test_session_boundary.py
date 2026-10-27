"""Real HTTP and SQLite: no draft or project may move across a Cookie rotation."""
from dataclasses import replace
import threading
import unittest
import test_composed_http as composed


class SessionBoundaryHTTPTests(unittest.TestCase):
    setUp=composed.ComposedHTTPTests.setUp
    close=composed.ComposedHTTPTests.close
    start=composed.ComposedHTTPTests.start
    request=composed.ComposedHTTPTests.request
    session=composed.ComposedHTTPTests.session

    def test_new_cookie_and_csrf_cannot_authorize_old_context_creates_or_drafts(self):
        old_cookie,old=self.session();new_cookie,new=self.session()
        payloads=[('/projects','POST',{'name':'不得跨工作区创建'}),('/drafts/browser','PUT',
            {'expectedVersion':0,'content':{'workflow':{'new-project':{'name':'旧工作区未建项目'}},'accountSelection':None}})]
        for path,method,body in payloads:
            for context in (old['session']['id'],''):
                status,_,result=self.request(path,method,cookie=new_cookie,csrf=new['csrfToken'],body=body,
                    extra_headers={'X-Asset-Lab-Session':context})
                self.assertEqual((status,result['error']['code']),(409,'WORKSPACE_CONTEXT_CHANGED'))
        self.assertEqual(self.request('/projects',cookie=new_cookie)[2]['data']['items'],[])
        self.assertEqual(self.request('/drafts/browser',cookie=new_cookie)[2]['data']['version'],0)
        self.assertEqual(self.request('/drafts/browser',cookie=old_cookie)[2]['data']['version'],0)

    def test_request_authenticated_before_rotation_is_rejected_inside_storage_transaction(self):
        payloads=[('/projects','POST',{'name':'轮换期间创建'}),('/drafts/browser','PUT',
            {'expectedVersion':0,'content':{'workflow':{'new-project':{'name':'轮换期间草稿'}},'accountSelection':None}})]
        for path,method,body in payloads:
            with self.subTest(path=path):
                cookie,data=self.session();entered=threading.Event();release=threading.Event();results=[]
                route,_=self.app.router.match(method,'/api/v1'+path)
                def delayed(ctx,params):
                    entered.set()
                    if not release.wait(3):raise RuntimeError('test barrier timed out')
                    return route.handler(ctx,params)
                index=self.app.router.routes.index(route);self.app.router.routes[index]=replace(route,handler=delayed)
                thread=threading.Thread(target=lambda:results.append(self.request(path,method,cookie=cookie,csrf=data['csrfToken'],body=body)))
                thread.start()
                try:
                    self.assertTrue(entered.wait(2))
                    ctx=self.app.services.sessions.bootstrap(cookie).context
                    rotated=self.app.services.sessions.rotate(ctx)
                finally:release.set();thread.join(3);self.app.router.routes[index]=route
                self.assertEqual(results[0][0],401)
                fresh=rotated.set_cookie.split(';',1)[0]
                self.assertEqual(self.request('/projects',cookie=fresh)[2]['data']['items'],[])
                self.assertEqual(self.request('/drafts/browser',cookie=fresh)[2]['data']['version'],0)

    def test_anonymous_bootstrap_requires_explicit_same_origin_action_and_rejects_live_cookie(self):
        cookie,data=self.session();path='/session/anonymous';body={'confirmNewWorkspace':True}
        action={'X-Asset-Lab-Action':'new-anonymous-workspace'}
        self.assertEqual(self.request(path,'POST',body=body)[0],403)
        self.assertEqual(self.request(path,'POST',body=body,extra_headers={**action,'Origin':'https://other.invalid'})[0],403)
        self.assertEqual(self.request(path,'POST',body={'confirmNewWorkspace':True,'tenantId':data['tenant']['id']},extra_headers=action)[0],422)
        self.assertEqual(self.request(path,'POST',cookie=cookie,body=body,extra_headers=action)[0],409)
        now=self.app.services.storage.clock();self.app.services.storage.clock=lambda:now+100*86400
        self.assertEqual(self.request('/session',cookie=cookie)[0],401)
        status,headers,result=self.request(path,'POST',cookie=cookie,body=body,extra_headers=action)
        self.assertEqual(status,200);self.assertNotEqual(result['data']['tenant'],data['tenant'])
        self.assertIn('Path=/asset-lab/',headers['Set-Cookie'])
        self.assertEqual(self.request('/projects',cookie=headers['Set-Cookie'].split(';',1)[0])[2]['data']['items'],[])
        self.assertFalse(result['data']['workspace']['ownerBound'])
