"""Official LibTV CLI adapter. No private HTTP endpoints or credential exports."""
import hashlib
import json
import os
import re
import subprocess
import threading
from pathlib import Path
from .lovart import ProviderError


class LibTV:
    name = 'libtv'
    default_model = 'lib-image-2.5-s'

    def __init__(self, root, binary=None):
        self.root = Path(root).resolve()
        self.binary = Path(binary or Path.home() / '.libtv/libtv')
        tag = hashlib.sha256(str(self.root).encode()).hexdigest()[:16]
        self.runtime = Path.home() / '.libtv/workbench' / tag
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.models, self.schemas, self.account = [], {}, {}
        self.login_url, self.login_pending, self.login_error = None, False, None

    @property
    def installed(self):
        return self.binary.is_file() and os.access(self.binary, os.X_OK)

    def call(self, *args, timeout=90, plain=False):
        if not self.installed:
            raise ProviderError('LibTV CLI 尚未安装。')
        try:
            p = subprocess.run([str(self.binary), *map(str, args)], cwd=self.runtime,
                               capture_output=True, text=True, timeout=timeout, start_new_session=True)
        except subprocess.TimeoutExpired:
            raise ProviderError('LibTV 操作未及时返回；请核对原画布，未自动重发。') from None
        if p.returncode:
            # Never expose raw CLI output: it can contain account credentials or signed URLs.
            raw = p.stderr.lower()
            if any(x in raw for x in ['未登录', '登录已过期', 'unauthorized', '401']):
                raise ProviderError('LibTV 登录已失效，请重新登录后验证连接。')
            if 'watermark' in raw or '水印' in raw:
                raise ProviderError('下载水印设置与 LibTV 会员状态不一致，请切换下载设置后重新收图。')
            raise ProviderError('LibTV 未完成此操作，请打开任务原画布核对；没有自动重复生成。')
        if plain:
            return p.stdout.strip()
        try:
            return json.loads(p.stdout)
        except ValueError:
            raise ProviderError('LibTV 返回格式无法解析，请核对原画布。') from None

    def check(self):
        state = self.call('status')
        if not state.get('auth', {}).get('loggedIn'):
            raise ProviderError('请先登录 LibTV，再验证连接。')
        account = self.call('account', 'info')
        self.account = account.get('activeAccount', {})
        self.models = self.call('model', 'search', '--type', 'image').get('matches', [])
        if not self.models:
            raise ProviderError('此账号未返回可用的图片模型。')
        return self.public_info()

    def public_info(self):
        return {'installed': self.installed, 'version': '1.2.0',
                'accountName': self.account.get('accountName', 'LibTV 已登录账号'),
                'models': [{k: m.get(k) for k in ('modelKey', 'modelName', 'description')}
                           for m in self.models if not m.get('autoPick')],
                'loginPending': self.login_pending, 'loginUrl': self.login_url,
                'loginError': self.login_error}

    def start_login(self):
        if self.login_pending:
            return self.public_info()
        if not self.installed:
            raise ProviderError('请先安装官方 LibTV CLI。')
        self.login_url, self.login_error, self.login_pending = None, None, True
        p = subprocess.Popen([str(self.binary), 'login', 'web'], cwd=self.runtime,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        ready = threading.Event()
        def collect():
            try:
                for line in p.stderr:
                    match = re.search(r'https://www\.liblib\.tv/\S+', line)
                    if match and 'callback_url=' in match.group():
                        self.login_url = match.group()
                        ready.set()
                p.wait()
                if p.returncode:
                    self.login_error = '登录未完成，请重新发起登录。'
            finally:
                self.login_pending = False
                self.login_url = None
                ready.set()
                p.stdout.close()
                p.stderr.close()
        threading.Thread(target=collect, daemon=True).start()
        ready.wait(5)
        return self.public_info()

    def model(self, key):
        entry = next((m for m in self.models if m['modelKey'] == key and not m.get('autoPick')), None)
        if not entry:
            raise ProviderError('请选择账号模型列表中明确的图片模型。')
        if key not in self.schemas:
            self.schemas[key] = self.call('model', key)['schema']
        return entry, self.schemas[key]

    def validate(self, job):
        if job.get('videoEnabled') or len(job.get('outputs', [])) != 1:
            raise ProviderError('当前接入只执行单张图片；视频和多视角批量任务尚未开放。')
        entry, schema = self.model(job.get('modelKey'))
        props = schema.get('properties', {})
        if job.get('generationCount',1) not in props.get('count',[1]):
            raise ProviderError('该模型不支持本次出图张数。')
        ratio = job['outputs'][0]['ratio']
        ratios = [v.get('value') if isinstance(v, dict) else v for v in props.get('ratio', {}).get('enum', [])]
        if ratio not in ratios:
            raise ProviderError('这个模型未声明支持所选画幅，请换一个图片模型。')
        mode = props.get('modeType', {}).get('items', {})
        bounds = mode.get('image2image')
        if not bounds or not bounds[0] <= len(job['inputs']) <= bounds[1]:
            raise ProviderError('这个模型的参考图数量不符合任务要求。')
        paths = []
        for name in job['inputs']:
            path = (self.root / name).resolve()
            if not path.is_relative_to(self.root) or not path.is_file() or path.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp'):
                raise ProviderError('参考图必须是项目内已有的图片。')
            if path.stat().st_size > 25 * 1024 * 1024:
                raise ProviderError('参考图超过 25 MB，请先缩小图片。')
            paths.append(path)
        return entry, schema, paths

    def prepare(self, job, update):
        entry, schema, paths = self.validate(job)
        current = self.call('account', 'info').get('activeAccount', {})
        if str(current.get('accountId')) != str(job.get('accountId')):
            raise ProviderError('LibTV 当前账号或空间已变化，请重新连接并创建新任务。')
        if not job.get('projectId'):
            name = '大师兄 · ' + job['title'] + ' · ' + job['id']
            # Resolve an earlier successful create before retrying after an ambiguous reply.
            listed = self.call('project', 'list', '--name', job['id'][-8:])
            matches = [p for p in listed.get('projectMetaList', [])
                       if p.get('name') in (name, '大师兄 · ' + job['title'] + ' · ' + job['id'][-8:])]
            if len(matches) > 1:
                raise ProviderError('找到多个同名测试画布，请先指定原画布，未重复创建。')
            project = matches[0] if matches else self.call('project', 'create', name)
            project_id = project.get('uuid') or project.get('projectUuid')
            if not project_id:
                listed = self.call('project', 'list', '--name', job['id'])
                matches = [p for p in listed.get('projectMetaList', []) if p.get('name') == name]
                project_id = matches[0].get('uuid') if len(matches) == 1 else None
            if not project_id:
                raise ProviderError('LibTV 未返回画布编号，未提交生成。')
            job['projectId'] = project_id
            update(projectId=project_id, projectUrl='https://www.liblib.tv/canvas?projectId=' + project_id)
        project_id = job['projectId']
        refs = list(job.get('referenceNodes', []))
        for i, path in enumerate(paths):
            if i < len(refs):
                continue
            uploaded = self.call('upload', '参考图-' + str(i + 1), '-p', project_id, '-t', 'image', '-f', path, timeout=180)
            node = uploaded.get('nodeKey')
            if not node:
                raise ProviderError('参考图上传未返回节点编号，未提交生成。')
            refs.append(node)
            update(referenceNodes=refs)
        prompt = '\n\n'.join([job['basePrompt'], '最终输出规格（优先）：' + job['outputRequirements'],
                              '本次修改要求：' + (job.get('additionalPrompt') or '沿用已确认的人物身份与画风。'),
                              '每张输出都是一个完整画面，不把不同候选拼在同一张图。' if job.get('phase')=='style' else '只生成一张静态资产图，按指定的资产版式排列。'])
        if not job.get('nodeKey'):
            args = ['node', '--x', '850', '--y', '100', 'create', '生成-' + job['id'], '-p', project_id,
                    '-t', 'image', '--prompt', prompt, '-s', 'model=' + entry['modelName'],
                    '-s', 'ratio=' + job['outputs'][0]['ratio'], '-s', 'count='+str(job.get('generationCount',1)), '-s', 'modeType=image2image']
            for name,value in job.get('modelSettings',{}).items():
                if name not in ('stylize','weird','chaos','quality','resolution'):raise ProviderError('不支持的图片模型设置。')
                args+=['-s',name+'='+str(value)]
            for node in refs:
                args += ['--left', node]
            node = self.call(*args)
            key = node.get('nodeKey') or node.get('newNodeKey')
            if not key:
                raise ProviderError('LibTV 未返回生成节点编号，未提交生成。')
            job['nodeKey'] = key
            update(nodeKey=key, modelName=entry['modelName'], modelVendor=schema.get('modelVendor'),
                   effectivePrompt=prompt, modelSchema=schema)
        return project_id, job['nodeKey']

    def run(self, project, node):
        # CLI owns polling and canvas writeback. The worker waits; page lifetime is irrelevant.
        return self.call('node', node, '-p', project, '--run', timeout=None)

    def recover_result(self, project, node):
        result = self.call('node', node, '-p', project)
        data = result.get('data', result.get('node', {}).get('data', {}))
        if data.get('url') and data.get('taskInfo', {}).get('status') == 2:
            return result
        raise ProviderError('原生成结果尚未确认成功。请查看 LibTV 原画布；系统不会重新扣分生成。')

    def download(self, job):
        images=self.download_images(job)
        if len(images)!=1:raise ProviderError('本次返回多张图片，请按候选批次收图。')
        return images[0]

    def download_images(self, job):
        folder = self.runtime / 'downloads' / job['id']
        folder.mkdir(parents=True, exist_ok=True)
        output = self.call('download', '-n', job['nodeKey'], '-p', job['projectId'],
                           '--watermark', str(bool(job.get('downloadWatermark', False))).lower(),
                           '-o', folder, timeout=180, plain=True)
        files = [Path(line.strip()).resolve() for line in output.splitlines() if line.strip()]
        if not files or any(not p.is_relative_to(folder.resolve()) or not p.is_file() for p in files):
            raise ProviderError('下载结果路径无法核验，原任务已保留。')
        from PIL import Image
        import io,zipfile
        blobs=[]
        for path in files:
            if path.stat().st_size > 160 * 1024 * 1024:raise ProviderError('下载文件超出接收范围。')
            if path.suffix.lower()=='.zip':
                with zipfile.ZipFile(path) as z:
                    members=[i for i in z.infolist() if not i.is_dir() and Path(i.filename).suffix.lower() in ('.png','.jpg','.jpeg','.webp') and not i.filename.startswith('__MACOSX/')]
                    if len(members)>4 or sum(i.file_size for i in members)>160*1024*1024:raise ProviderError('图片压缩包超出接收范围。')
                    # Decode members in memory; do not trust archive filenames as extraction paths.
                    blobs.extend(z.read(i) for i in sorted(members,key=lambda i:i.filename))
            else:blobs.append(path.read_bytes())
        if len(blobs)!=job.get('generationCount',1):raise ProviderError('返回候选数量与任务不一致，请核对原画布。')
        images=[]
        for raw in blobs:
            if len(raw)>40*1024*1024:raise ProviderError('单张图片超过接收范围。')
            with Image.open(io.BytesIO(raw)) as im:
                if im.width*im.height>40000000:raise ProviderError('图片尺寸超过当前工作台接收范围。')
                im.load();data=io.BytesIO();im.convert('RGB').save(data,'PNG')
                images.append((data.getvalue(),[im.width,im.height]))
        return images
