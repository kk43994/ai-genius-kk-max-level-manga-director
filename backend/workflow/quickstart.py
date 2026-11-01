"""Atomic, idempotent import. Semantic extraction belongs exclusively to AI."""
import base64
import copy
import hashlib
import json
import re
from pathlib import PurePosixPath

from .errors import WorkflowError, invalid, public_input, tenant
from .intake import decode_script, MAX_TEXT
from .service import new_id, now


def start(workflow, ctx, payload):
    public_input(payload, {'text', 'filename', 'contentBase64', 'idempotencyKey'})
    key = payload.get('idempotencyKey')
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9._:-]{8,200}', key):
        invalid('请使用有效的开始请求编号。')
    if 'text' in payload:
        text = payload['text']
        if not isinstance(text, str) or len(text) > MAX_TEXT or 'contentBase64' in payload:
            invalid('请粘贴不超过 25 万字的剧本，或选择一个剧本文件。')
        source = {'filename': payload.get('filename', '我的剧本.txt'),
                  'contentBase64': base64.b64encode(text.encode('utf-8')).decode()}
    else:
        source = {k: payload.get(k) for k in ('filename', 'contentBase64')}
    script, raw = decode_script(source)
    request_hash = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    start_id = 'start_' + hashlib.sha256(key.encode()).hexdigest()
    with workflow.repository.transaction(ctx, write=True) as tx:
        previous = tx.state['starts'].get(start_id)
        if previous:
            if previous['requestHash'] != request_hash:
                raise WorkflowError('IDEMPOTENCY_CONFLICT', '该请求已经保存了另一份剧本，请重新开始。', 409)
            project = workflow._project(tx, previous['projectId'])
            script = tx.state['scripts'][previous['scriptId']]
            return {'project': workflow._public_project(project), 'script': workflow._public_script(script),
                    'plan': copy.deepcopy(project['plan']), 'duplicate': True}
        pid, sid, timestamp = new_id('prj'), new_id('scr'), now()
        entities = []
        project = {'id': pid, 'tenantId': tenant(ctx), 'name': PurePosixPath(script['filename']).stem[:120],
                   'description': '', 'version': 1, 'createdAt': timestamp, 'updatedAt': timestamp,
                   'scriptIds': [sid], 'status': 'active',
                   'plan': {'version': 1, 'needsReview': True, 'entities': entities, 'stylePrompt': '',
                            'styleVersion': 1, 'updatedAt': timestamp}}
        script.update(id=sid, projectId=pid, version=1, importedAt=timestamp,
                      analysisStatus='not_started', analysis=workflow.capabilities()['analysis'], blobId=tx.put_blob(raw))
        tx.state['projects'][pid] = project
        tx.state['scripts'][sid] = script
        tx.state['starts'][start_id] = {'requestHash': request_hash, 'projectId': pid, 'scriptId': sid}
        return {'project': workflow._public_project(project), 'script': workflow._public_script(script),
                'plan': copy.deepcopy(project['plan']), 'duplicate': False}


def analyze(workflow, ctx, project_id, script_id, payload):
    if not getattr(workflow, 'analysis', None):
        raise WorkflowError('ANALYSIS_UNAVAILABLE', 'AI 分析服务尚未启用；原文已保存，不会使用本地规则替代。', 503)
    return workflow.analysis.start(ctx, project_id, script_id, payload)
