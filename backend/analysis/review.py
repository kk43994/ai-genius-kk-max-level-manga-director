"""Show returned analysis before validation; manual corrections never call AI."""
import copy
import hashlib
import json
import uuid
from jsonschema import Draft202012Validator
from backend.workflow.errors import WorkflowError, public_input
from backend.workflow.service import now
from .contract import SCHEMA, evidence_issues, validate_result


def editable_structure(result):
    # Empty human-entered strings remain editable cards. Contract errors still
    # appear and prevent treating the incomplete draft as verified analysis.
    errors = Draft202012Validator(SCHEMA).iter_errors(result)
    return all(error.validator in ('minLength', 'pattern', 'minimum') for error in errors)


def decode(text):
    if not isinstance(text, str) or len(text) > 2_000_000: return None
    text = text.strip()
    if text.startswith('```json\n') and text.endswith('```'): text = text[8:-3].strip()
    elif text.startswith('```\n') and text.endswith('```'): text = text[4:-3].strip()
    try: result = json.loads(text)
    except (ValueError, RecursionError): return None
    return result if isinstance(result, dict) else None


def inspect(result, script):
    errors = list(Draft202012Validator(SCHEMA).iter_errors(result))
    if errors:
        return [{'code': 'structure', 'path': '.'.join(map(str, e.absolute_path)),
                 'message': '此字段格式需要修正：' + e.message[:180]} for e in errors[:50]]
    issues = []
    for issue in evidence_issues(result, script):
        path = issue['path'].removeprefix('result.')
        quote = 'returnedQuote' in issue
        parts = path.split('.')
        row = result[parts[0]][int(parts[1])] if len(parts) > 1 and parts[1].isdigit() else {}
        issues.append({'code': 'source_quote' if quote else 'dialogue',
            'path': path + '.quote' if quote else path,
            'label': row.get('name') or row.get('title') or row.get('summary') or '原文引用',
            'message': issue['problem'], 'sourceText': issue['sourceAtLines'],
            'returnedText': issue.get('returnedQuote', issue.get('returnedText', ''))})
    try: validate_result(result, script)
    except WorkflowError as error:
        if not issues or str(error) not in ('AI 引用的文字与原文不一致。', 'AI 台词与原文不逐字一致，已阻止使用改写的台词。'):
            issues.append({'code': 'association', 'path': '', 'message': str(error)})
    return issues


def optional(store, ctx, collection, identity):
    try: return store.get(ctx, collection, identity)
    except Exception as error:
        if getattr(error, 'code', None) != 'NOT_FOUND': raise
        return None


def result_hash(data):
    value = data.get('analysisDraft') or data.get('result') or data.get('draft')
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def present(service, ctx, row, public):
    from .service import ACTIVE
    data = row['data']
    script = service.services.workflow.get_script(ctx, data['projectId'], data['scriptId'])
    raw = data.get('analysisDraft')
    preview = copy.deepcopy(data.get('result') or (decode(raw) if raw is not None else data.get('draft')))
    review = optional(service.store, ctx, 'analysis.reviews', row['id'])
    public.update(reviewVersion=review['version'] if review else 0, resultHash=result_hash(data),
                  validationIssues=[], draftResult=None, returnedText=raw, manuallyEdited=bool(review),
                  structuredDraft=False, canReadOriginal=False)
    if review:
        preview = copy.deepcopy(review['data']['result'])
        public.update(canResumeReview=False, canRepairResult=False)
    if preview is not None:
        issues = inspect(preview, script)
        public.update(validationIssues=issues, structuredDraft=editable_structure(preview),
                      draftResult=preview if issues else None, result=None if issues else preview)
        if data['status'] not in ACTIVE:
            public.update(status='needs_review' if issues else 'ready', canRefresh=False, error=None,
                message=f'分析结果已返回，有 {len(issues)} 处标红待核对；可直接修改保存。' if issues
                else '分析结果已展示，可对照原文修改后继续制作。')
    elif raw and data['status'] not in ACTIVE:
        public.update(status='needs_review', error=None, canRefresh=False,
                      message='AI 已返回内容，结构尚不完整；原始结果已保留，可手动修正。')
    if not raw and preview is None and data['status']=='failed' and data.get('steps', {}).get(data['phase'], {}).get('taskId'):
        public['canReadOriginal'] = data.get('error', {}).get('code') == 'ANALYSIS_RESULT_INVALID'
    first = data.get('draft')
    public['originalIssues'] = inspect(first, script) if first and first != preview else []
    return public


def save(service, ctx, identity, body):
    from .service import ACTIVE
    public_input(body, {'expectedVersion', 'expectedResultHash', 'result'})
    original = service._get(ctx, identity)
    data = original['data']
    script = service.services.workflow.get_script(ctx, data['projectId'], data['scriptId'])
    if data['status'] in ACTIVE:
        raise WorkflowError('ANALYSIS_RUNNING', '原任务仍在返回结果，修改草稿已保留，返回后再保存。', 409)
    if not any(data.get(key) for key in ('result', 'analysisDraft', 'draft')):
        raise WorkflowError('ANALYSIS_NOT_RETURNED', '尚未取得 AI 返回内容，请先读取原任务。', 409)
    edited = body.get('result')
    if not isinstance(edited, dict) or len(json.dumps(edited, ensure_ascii=False)) > 2_000_000:
        raise WorkflowError('ANALYSIS_EDIT_INVALID', '修改内容需为完整分析对象且不超过容量。', 422)
    issues = inspect(edited, script)
    with service.store.transaction(ctx) as tx:
        latest = tx.get(service.collection, identity)
        try: old = tx.get('analysis.reviews', identity)
        except Exception as error:
            if getattr(error, 'code', None) != 'NOT_FOUND': raise
            old = None
        if (latest['version'] != original['version'] or body.get('expectedResultHash') != result_hash(latest['data'])
            or type(body.get('expectedVersion')) is not int or body['expectedVersion'] != (old['version'] if old else 0)):
            raise WorkflowError('VERSION_CONFLICT', '分析已被另一页面更新，本机修改仍保留，请刷新核对。', 409)
        payload = {'jobId': identity, 'result': copy.deepcopy(edited), 'validated': not issues, 'savedAt': now()}
        if old: tx.update('analysis.reviews', identity, payload, expected_version=old['version'])
        else: tx.create('analysis.reviews', payload, record_id=identity)
        tx.create('analysis.review_history', {**payload, 'reviewVersion': (old['version'] if old else 0)+1}, record_id='arh_'+uuid.uuid4().hex)
    return service.get(ctx, identity)
