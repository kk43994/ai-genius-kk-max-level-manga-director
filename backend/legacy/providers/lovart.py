"""Small Lovart Agent OpenAPI adapter; credentials stay in process memory.

Protocol reference: lovartai/lovart-skill, scripts/agent_skill.py.
No automatic POST retries, billing-mode changes, or high-cost confirmations.
"""
import hashlib
import hmac
import json
import time
import uuid
from urllib import request, parse, error


class ProviderError(Exception):
    pass


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Lovart:
    base = 'https://lgw.lovart.ai'
    tool = 'generate_image_gpt_image_2_5_flare'

    def __init__(self, access_key, secret_key):
        self.access_key, self.secret_key = access_key, secret_key

    def call(self, method, endpoint, body=None, query=None, key=None, content_type=None):
        path = '/v1/openapi' + endpoint
        stamp = str(int(time.time()))
        signature = hmac.new(self.secret_key.encode(), f'{method}\n{path}\n{stamp}'.encode(), hashlib.sha256).hexdigest()
        headers = {'X-Access-Key': self.access_key, 'X-Timestamp': stamp,
                   'X-Signature': signature, 'X-Signed-Method': method, 'X-Signed-Path': path}
        if body is not None:
            headers['Content-Type'] = content_type or 'application/json'
        if key:
            headers['Idempotency-Key'] = key
        data = body if isinstance(body, bytes) else json.dumps(body).encode() if body is not None else None
        url = self.base + path + ('?' + parse.urlencode(query) if query else '')
        try:
            with request.build_opener(NoRedirect()).open(request.Request(url, data=data, headers=headers, method=method), timeout=45) as response:
                value = json.loads(response.read(4 * 1024 * 1024))
        except error.HTTPError as exc:
            raise ProviderError(f'Lovart 返回 HTTP {exc.code}，请检查连接或账户权限。') from None
        except (OSError, ValueError):
            raise ProviderError('暂未收到 Lovart 的有效回复。') from None
        if not isinstance(value, dict) or value.get('code', 0) != 0:
            raise ProviderError('Lovart 未接受请求，请检查账户权限和额度。')
        return value.get('data', value)

    def check(self):
        self.call('POST', '/mode/query', {}, key=uuid.uuid4().hex)

    def project(self, job):
        result = self.call('POST', '/project/save', {
            'project_id': '', 'project_name': job['title'], 'project_type': 3,
            'canvas': '', 'project_cover_list': [], 'pic_count': 0,
        }, key=job['id'] + '-project')
        if not result.get('project_id'):
            raise ProviderError('Lovart 未返回项目编号。')
        return result['project_id']

    def upload(self, path):
        if path.stat().st_size > 25 * 1024 * 1024:
            raise ProviderError('参考图片超过 25 MB，请压缩后再提交。')
        boundary = uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="reference{path.suffix}"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode()
        body += path.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
        result = self.call('POST', '/file/upload', body, content_type='multipart/form-data; boundary=' + boundary)
        if not result.get('url'):
            raise ProviderError('Lovart 未返回参考图地址。')
        return result['url']

    def submit(self, job, project_id, attachments):
        prompt = '\n\n'.join([
            '仅生成一张静态图片。禁止生成视频、音频、动画或执行其他任务。使用 GPT Image 2.5。',
            job['basePrompt'], job['outputRequirements'], '本次补充要求：' + (job['additionalPrompt'] or '无'),
            '参考附件保持人物身份和已选画风。只交付要求的图片。',
        ])
        result = self.call('POST', '/chat', {
            'project_id': project_id, 'prompt': prompt, 'attachments': attachments, 'mode': 'fast',
            'tool_config': {'prefer_tool_categories': {'IMAGE': [self.tool]}, 'include_tools': [self.tool]},
        }, key=job['id'])
        if not result.get('thread_id'):
            raise ProviderError('提交后未收到任务编号，不能安全自动重发。')
        return result['thread_id']

    def status(self, thread_id):
        return self.call('GET', '/chat/status', query={'thread_id': thread_id})

    def result(self, thread_id):
        return self.call('GET', '/chat/result', query={'thread_id': thread_id})
