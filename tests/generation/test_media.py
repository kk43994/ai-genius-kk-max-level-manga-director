import io
import socket
import unittest

from backend.generation import GenerationError, SafeMediaTransfer
from backend.generation.media import inspect_image
from helpers import png


class Response:
    def __init__(self, body, status=200, content_type='image/png', length=None):
        self.body = io.BytesIO(body)
        self.status, self.kind, self.length = status, content_type, length
    def getheader(self, name):
        return self.kind if name == 'Content-Type' else self.length if name == 'Content-Length' else None
    def read(self, limit):
        return self.body.read(limit)


class Connection:
    def __init__(self, response):
        self.response, self.requests, self.closed = response, [], False
    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed = True


class MediaTests(unittest.TestCase):
    def setUp(self):
        self.raw = png()
        self.conn = Connection(Response(self.raw, length=str(len(self.raw))))
        self.connections = []
        self.addresses = ['93.184.216.34']
        def resolver(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in self.addresses]
        def connector(host, address, timeout):
            self.connections.append((host, address, timeout))
            return self.conn
        self.media = SafeMediaTransfer(['media.invalid'], evidence='SYNTHETIC TEST ONLY', resolver=resolver, connector=connector)
    def get(self, url='https://media.invalid/image?signature=private', **kwargs):
        return self.media.get(url, mime='image/png', max_bytes=1000, max_pixels=10000, **kwargs)
    def error(self, code, fn):
        with self.assertRaises(GenerationError) as cm:
            fn()
        self.assertEqual(cm.exception.code, code)
        self.assertNotIn('signature', str(cm.exception))

    def test_dns_is_pinned_and_no_authorization_or_cookies_sent(self):
        self.assertEqual(self.get(), self.raw)
        self.assertEqual(self.connections[0][:2], ('media.invalid', '93.184.216.34'))
        headers = self.conn.requests[0][1]['headers']
        self.assertNotIn('Authorization', headers)
        self.assertNotIn('Cookie', headers)
        self.assertTrue(self.conn.closed)

    def test_private_loopback_linklocal_and_mixed_dns_are_blocked(self):
        for ip in ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', 'fc00::1', '0.0.0.0']:
            self.addresses = ['93.184.216.34', ip]
            self.error('UNSAFE_MEDIA_URL', self.get)
        self.assertEqual(self.connections, [])

    def test_only_exact_https_host_and_default_port(self):
        for url in ['http://media.invalid/x', 'https://media.invalid.evil/x', 'https://evil.invalid/x',
                    'https://user:password@media.invalid/x', 'https://media.invalid:444/x',
                    'https://media.invalid/x#fragment', 'file:///etc/passwd', 'https://media.invalid/\nheader']:
            self.error('UNSAFE_MEDIA_URL', lambda: self.get(url))
        self.assertEqual(self.connections, [])

    def test_redirect_is_not_followed(self):
        self.conn.response = Response(b'', status=302)
        self.error('MEDIA_TRANSFER_FAILED', self.get)
        self.assertEqual(len(self.connections), 1)
        self.assertTrue(self.conn.closed)

    def test_declared_and_streamed_size_and_short_body(self):
        self.conn.response = Response(self.raw, length='1001')
        self.error('OUTPUT_INVALID', self.get)
        self.conn.response = Response(b'x' * 1001)
        self.error('OUTPUT_INVALID', self.get)
        self.conn.response = Response(self.raw, length='999')
        self.error('MEDIA_TRANSFER_FAILED', self.get)

    def test_mime_hash_and_pixel_limits(self):
        self.conn.response = Response(self.raw, content_type='text/html')
        self.error('OUTPUT_INVALID', self.get)
        self.conn.response = Response(self.raw)
        self.error('OUTPUT_INVALID', lambda: self.get(sha256='0' * 64))
        self.error('OUTPUT_INVALID', lambda: inspect_image(self.raw, 'image/png', max_pixels=10))
        self.error('OUTPUT_INVALID', lambda: inspect_image(b'<html>bad</html>', 'image/png'))

    def test_default_transfer_has_no_unverified_host(self):
        self.error('TRANSFER_HOST_UNVERIFIED', lambda: SafeMediaTransfer().get(
            'https://media.invalid/x', mime='image/png', max_bytes=1000, max_pixels=10000))

    def test_upload_is_bounded_and_does_not_follow_redirect(self):
        self.conn.response = Response(b'', status=204)
        self.media.put('https://media.invalid/upload', self.raw)
        self.assertEqual(self.conn.requests[0][0][0], 'PUT')
        self.assertNotIn('Content-Type', self.conn.requests[0][1]['headers'])
        self.conn.response = Response(b'', status=307)
        self.error('MEDIA_TRANSFER_FAILED', lambda: self.media.put('https://media.invalid/upload', self.raw))


if __name__ == '__main__':
    unittest.main()

class FakeIPCompatibilityTests(unittest.TestCase):
    def test_fake_ip_uses_public_resolver_and_pins_tls_host(self):
        from backend.generation.media import PublicMediaResolver
        import socket
        hits=[]
        def query(host):
            hits.append(host)
            return {'Status':0,'Question':[{'name':host+'.','type':1}],
                    'Answer':[{'type':1,'data':'1.1.1.1'}]}
        system=lambda host,port,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('198.18.0.4',443))]
        r=PublicMediaResolver(['media.example'],system=system,query=query)
        self.assertEqual(r('media.example',443,type=socket.SOCK_STREAM)[0][4][0],'1.1.1.1')
        r('media.example',443,type=socket.SOCK_STREAM)
        self.assertEqual(hits,['media.example'])
        with self.assertRaises(GenerationError):r('untrusted.example',443,type=socket.SOCK_STREAM)
    def test_private_dns_is_not_replaced_or_allowed(self):
        from backend.generation.media import PublicMediaResolver
        import socket
        system=lambda host,port,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        r=PublicMediaResolver(['media.example'],system=system,query=lambda _:self.fail('No DNS fallback for private hosts'))
        transfer=SafeMediaTransfer(['media.example'],evidence='synthetic test',resolver=r)
        with self.assertRaises(GenerationError):transfer._target('https://media.example/image.png')
    def test_bad_doh_response_and_private_answer_rejected(self):
        from backend.generation.media import PublicMediaResolver
        import socket
        system=lambda host,port,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('198.18.0.4',443))]
        for body in ({'Status':0,'Question':[{'name':'other.example','type':1}],'Answer':[{'type':1,'data':'1.1.1.1'}]},
                     {'Status':0,'Question':[{'name':'media.example','type':1}],'Answer':[{'type':1,'data':'10.0.0.1'}]}):
            r=PublicMediaResolver(['media.example'],system=system,query=lambda _:body)
            with self.assertRaises(GenerationError):r('media.example',443,type=socket.SOCK_STREAM)
