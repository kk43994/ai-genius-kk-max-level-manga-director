"""Readable production drafts and precise local validation feedback; no AI calls."""
import json
from jsonschema import Draft202012Validator
from backend.workflow.errors import WorkflowError
from .production import SCHEMA, validate


def decode(text):
    if not isinstance(text, str) or len(text) > 2_000_000:
        return None
    text = text.strip()
    if text.startswith('```json\n') and text.endswith('```'):
        text = text[8:-3].strip()
    try:
        value = json.loads(text)
    except (ValueError, RecursionError):
        return None
    return value if Draft202012Validator(SCHEMA).is_valid(value) else None


def inspect(result, script, context):
    """Identify editable quote locations without changing model/source content."""
    errors = list(Draft202012Validator(SCHEMA).iter_errors(result))
    if errors:
        return [{'code': 'structure', 'label': '方案结构',
                 'path': '.'.join(map(str, e.absolute_path)),
                 'message': '此字段的类型或长度不符合要求，请调整后保存。'} for e in errors[:20]]
    lines, issues = script['text'].splitlines(), []
    for collection in ('assets', 'shots'):
        for index, item in enumerate(result[collection]):
            label = item.get('name') or f"镜头 {index+1:03d} · {item['purpose']}"
            for n, evidence in enumerate(item['evidence']):
                valid_range = 1 <= evidence['startLine'] <= evidence['endLine'] <= len(lines)
                source = '\n'.join(lines[evidence['startLine']-1:evidence['endLine']]) if valid_range else ''
                if not valid_range or evidence['quote'] not in source:
                    issues.append({'code': 'source_quote', 'label': label,
                        'path': f'{collection}.{index}.evidence.{n}',
                        'message': '引用经过缩写或遗漏内容，请对照右侧原文修改。' if valid_range else '引用行号超出原文范围，请修改行号和引用。',
                        'sourceText': source, 'startLine': evidence['startLine'], 'endLine': evidence['endLine']})
    try:
        validate(result, script, context)
    except WorkflowError as error:
        if not issues or str(error) != '制作方案的原文引用不一致。':
            issues.append({'code': 'association', 'label': '物料与镜头关联', 'path': '', 'message': str(error)})
    return issues
