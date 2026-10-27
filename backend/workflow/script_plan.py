"""Conservative, offline extraction of explicitly labelled screenplay assets.

This is not an LLM. Every extracted asset points to literal source text; prose
without screenplay structure remains unparsed rather than inventing entities.
"""
import hashlib
import re

VERSION = 'screenplay-rules-v3'
LABELS = {'角色': 'character', '人物': 'character', '出场人物': 'character',
          '场景': 'scene', '地点': 'scene', '道具': 'prop', '关键道具': 'prop', '异象': 'effect'}
NON_SPEAKERS = set(LABELS) | {'时间', '对白', '旁白', '画外音', '字幕', '音效', '音乐', '动作',
    '镜头', '画面', '转场', '内景', '外景', '日', '夜', '备注', '标题', '剧名', '风格', '视觉风格'}
NUMBERED_CUE = re.compile(r'(?:场景|镜头|闪回|画面|分镜|段落|转场|旁白|字幕|音效|音乐)[一二三四五六七八九十百零〇\dA-Za-z]+')


def extract_plan(text):
    rows, seen, warnings = [], set(), []
    title, style = '', ''
    section = None

    def add(category, name, quote, description=''):
        name = re.sub(r'^[\s\-•·\d.、]+', '', name).strip(' 《》「」【】')
        if not name or len(name) > 60 or name in NON_SPEAKERS:
            return
        key = (category, name)
        if key in seen:
            return
        seen.add(key)
        if len(rows) >= 300:
            return
        rows.append({'id': 'ent_' + hashlib.sha256((category + '\0' + name).encode()).hexdigest()[:24],
            'category': category, 'name': name, 'description': (description or name)[:4000],
            'origin': 'script', 'quote': quote[:4000], 'variant': ''})

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            section = None
            continue
        content = re.sub(r'^#{1,6}\s*', '', line)
        header = re.fullmatch(r'(出场人物|关键道具|角色|人物|道具|异象)\s*[:：]?', content)
        if header:
            section = LABELS[header.group(1)]
            continue
        if section:
            definition = re.fullmatch(r'([^:：]{1,60})[:：]\s*(.+)', content)
            if definition:
                add(section, definition.group(1), line, definition.group(2))
                continue
        named_title = re.fullmatch(r'(?:剧名|标题)\s*[:：]\s*(.{1,120})', content)
        book_title = re.fullmatch(r'《([^》]{1,120})》', content)
        if not title and (named_title or book_title):
            title = (named_title or book_title).group(1)
            continue
        visual = re.fullmatch(r'(?:风格|视觉风格)\s*[:：]\s*(.{1,1000})', content)
        if visual:
            style = visual.group(1)
            continue
        labelled = re.fullmatch(r'(出场人物|关键道具|角色|人物|场景|地点|道具|异象)\s*[:：]\s*(.+)', content)
        if labelled:
            category, details = LABELS[labelled.group(1)], labelled.group(2)
            parts = re.split(r'[;；]', details) if re.search(r'[:：]', details) else re.split(r'[、,，;；]', details)
            for part in parts:
                name, *description = re.split(r'[:：—]|\s+-\s+', part, maxsplit=1)
                # Lists are reliable; long unstructured descriptions are not names.
                add(category, name, line, description[0].strip() if description else '')
            continue
        # Chinese numbered sluglines and English INT./EXT. locations.
        slug = re.fullmatch(r'(?:第[一二三四五六七八九十百\d]+场|场景[一二三四五六七八九十百\d]+|\d+[.\-]\d+|场\s*\d+)\s*[.、:：]?\s*(.+)', content)
        english = re.fullmatch(r'(?:INT\.?|EXT\.?|INT\.?/EXT\.?)\s+(.+)', content, re.I)
        bracket = re.fullmatch(r'[【\[](.+)[】\]]', content)
        scene = (slug or english)
        if not scene and bracket and re.search(r'(?:内景|外景|日|夜)', bracket.group(1)):
            scene = bracket
        if scene:
            place = re.sub(r'(?:^|[\s/—\-·]+)(?:内景|外景|内|外|日|夜|白天|夜晚|DAY|NIGHT)(?=$|[\s/—\-·]+)', ' ', scene.group(1), flags=re.I)
            place = re.sub(r'\s+', ' ', place).strip(' -—/·')
            add('scene', place, line)
            continue
        speaker = re.fullmatch(r'([\w\u4e00-\u9fff·]{1,20})(?:[（(][^）)]{0,100}[）)])?\s*[:：]\s*(.+)', content)
        if speaker and speaker.group(1) not in NON_SPEAKERS and not NUMBERED_CUE.fullmatch(speaker.group(1)):
            add('character', speaker.group(1), line)

    kinds = {r['category'] for r in rows}
    if not rows:
        warnings.append('未识别到明确的角色或场次标记。请使用“角色：”“场景：”“道具：”标注，或手工补充清单。')
    else:
        warnings.append('这是本地规则生成的初稿，请核对同名角色、别名和未标注的资产；没有推测原文未写明的外观。')
        if 'scene' not in kinds:
            warnings.append('未识别到场景，请补充场景标记或在清单中添加。')
        if 'prop' not in kinds:
            warnings.append('未找到明确的道具清单，请核对故事中是否有需要单独制作的道具。')
    if len(seen) > 300:
        warnings.append('剧本超过 300 项资产，本次仅提取前 300 项，请分项目处理。')
    return {'name': title, 'entities': rows, 'stylePrompt': style,
            'analysis': {'method': VERSION, 'configured': True, 'state': 'draft',
                'status': 'needs_review', 'warnings': warnings, 'count': len(rows),
                'message': '已按剧本标记提取初稿，等待核对。'}}
