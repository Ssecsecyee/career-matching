"""Storage for the blind test set (eval/gold.test.json), used by labeling_app.py.

The labeler sees only the posting text; nothing here proposes a label. Only skill names and
notes are written to the gold file - never posting text (it stays in data/real/, git-ignored).
Once sealed, the file is read-only for the app: the test is scored once against it.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

LEVELS = ('required', 'preferred', 'responsibility', 'mention')
RANK = {level: i for i, level in enumerate(LEVELS)}


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, doc):
    tmp = Path(path).with_suffix('.tmp')
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def split_names(text):
    """'Java, Kotlin , ,Go' -> ['Java', 'Kotlin', 'Go'] (order kept, duplicates dropped)."""
    seen, out = set(), []
    for part in (text or '').replace('\n', ',').split(','):
        name = part.strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append(name)
    return out


def build_label(levels, or_groups_text='', unsure_text='', note='', open_requirements=False):
    """levels: {level: [names]}. A skill written at two levels keeps the stronger one (labeling guide)."""
    best = {}
    for level in LEVELS:
        for name in levels.get(level, []):
            key = name.casefold()
            if key not in best or RANK[level] < RANK[best[key][0]]:
                best[key] = (level, name)
    label = {level: [name for lvl, name in best.values() if lvl == level] for level in LEVELS}
    groups = [split_names(line) for line in (or_groups_text or '').splitlines()]
    groups = [g for g in groups if len(g) >= 2]
    labeled = {name.casefold() for _, name in best.values()}
    missing = sorted({n for g in groups for n in g if n.casefold() not in labeled})
    if groups:
        label['_or_groups'] = groups
    unsure = split_names(unsure_text)
    if unsure:
        label['_unsure'] = unsure
    if note.strip():
        label['_note'] = note.strip()
    if open_requirements:
        label['_flags'] = ['open_requirements']
    label['_done'] = True
    moved = sorted(name for (lvl, name) in best.values()
                   if sum(name.casefold() in {n.casefold() for n in levels.get(l, [])} for l in LEVELS) > 1)
    return label, {'or_group_names_not_labeled': missing, 'kept_stronger_level': moved}


def save_label(path, posting_id, label):
    doc = load(path)
    if doc.get('status') == 'approved':
        raise PermissionError('봉인된 시험지는 고칠 수 없습니다.')
    if posting_id not in doc['labels']:
        raise KeyError(posting_id)
    doc['labels'][posting_id] = label
    write(path, doc)


def progress(doc):
    done = [pid for pid, lab in doc['labels'].items() if lab.get('_done')]
    return len(done), len(doc['labels'])


def seal(path, labeled_by):
    doc = load(path)
    done, total = progress(doc)
    if done != total:
        raise ValueError(f'아직 {total - done}건이 남았습니다.')
    doc['status'] = 'approved'
    doc['labeled_by'] = labeled_by
    doc['sealed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    write(path, doc)
    return doc
