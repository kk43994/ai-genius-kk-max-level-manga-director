"""Resolve human-edited speech without replacing the source analysis."""
import copy


def resolved_dialogues(source, shot):
    edits = {d['id']: d for d in shot.get('dialogueOverrides', [])}
    rows = []
    for identity in shot['dialogueIds']:
        original = source[identity]
        line = copy.deepcopy(original)
        if identity in edits:
            line.update(edits[identity])
            line.update(sourceText=original['text'], sourceSpeakerId=original.get('speakerId'),
                        sourceSpeakerLabel=original.get('speakerLabel'), sourceKind=original['kind'], edited=True)
        if not line.get('deleted'):
            rows.append(line)
    rows.extend(copy.deepcopy(d) | {'added': True, 'edited': True}
                for d in shot.get('dialogueAdditions', []) if not d.get('deleted'))
    rank = {identity: i for i, identity in enumerate(shot.get('dialogueOrder', []))}
    if rank:
        rows.sort(key=lambda d: rank.get(d['id'], 999))
    return rows
