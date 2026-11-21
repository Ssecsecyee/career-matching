"""Export stored Techmap postings in the teammate's extraction format (24 columns) — no new API call.

    python -m eval.techmap_export      # -> data/real/techmap/export/ (CSV with BOM, JSON, HTML; git-ignored)

Format: the teammate's "채용공고 추출 파일 형식 안내" — one row per posting, English column names,
lists/objects as JSON strings, original text kept as is, unknown values left blank with the reason
in field_status, dates without invented times, UTF-8 BOM CSV with standard escaping, JSON alongside.
Every value also carries where it came from, so a reader can tell source text from Techmap's own
tags, from our splitter's output and from blanks.
"""
import csv
import hashlib
import html
import json
import re
from pathlib import Path

from eval.techmap_view import get, pick, raw_items, tidy

ROOT = Path(__file__).resolve().parents[1]
JOBS = ROOT / 'data' / 'real' / 'jobs.json'
OUT = ROOT / 'data' / 'real' / 'techmap' / 'export'

BASE = ['source_id', 'source_url', 'title', 'company_name', 'tech_stacks', 'original_categories', 'addresses',
        'published_at', 'deadline_display_raw', 'recruitment_status', 'fetched_at', 'last_checked_at',
        'classification', 'field_status']
EXTENDED = ['job_id', 'source', 'source_version', 'content_hash', 'responsibilities', 'qualifications',
            'preferred_requirements', 'benefits', 'hiring_process', 'application_notes']
COLUMNS = BASE + EXTENDED
MEANING = {
    'source_id': '출처 사이트의 공고 ID', 'source_url': '상세 페이지 URL', 'title': '제목', 'company_name': '회사명',
    'tech_stacks': '기술스택', 'original_categories': '원래 카테고리', 'addresses': '주소', 'published_at': '확인된 등록일',
    'deadline_display_raw': '원문 마감 표시', 'recruitment_status': '모집 상태', 'fetched_at': '수집 시각',
    'last_checked_at': '마지막 확인 시각', 'classification': '수집 비교 분류', 'field_status': '필드별 확인 상태·출처',
    'job_id': 'MySQL 내부 공고 ID', 'source': '데이터 출처', 'source_version': '원문 버전', 'content_hash': '원문 해시',
    'responsibilities': '주요업무', 'qualifications': '자격요건', 'preferred_requirements': '우대사항',
    'benefits': '복지·혜택', 'hiring_process': '채용절차', 'application_notes': '지원 유의사항'}
# status of a value: where it came from
STATUS = {'source': ('원문 값', 'Techmap이 원 공고에서 옮긴 값'),
          'techmap': ('Techmap 가공', 'Techmap이 자체로 붙이거나 정리한 값'),
          'derived': ('우리 분할', '본문 한 덩어리를 우리 분할기(segment.py)가 나눈 결과'),
          'computed': ('계산', '우리가 규칙으로 계산한 값'),
          'missing': ('비움', '확인할 수 없어 비워 둠 — 이유는 field_status')}
SPLIT_NOTE = '본문이 한 덩어리로 와서 우리 분할기(segment.py)가 소제목 줄로 나눈 원문 줄 (요약 아님)'
COLUMN_NOTE = {
    'source_id': 'URL의 숫자 ID (잡코리아 GI_Read, 사람인 rec_idx). URL이 없으면 비움',
    'source_url': 'jsonLD.url — 원 공고 주소', 'title': 'Techmap title — 원 공고 제목',
    'company_name': 'jsonLD.hiringOrganization.name',
    'tech_stacks': 'Techmap skills — Techmap이 자동으로 단 태그, 원 공고의 기술스택 칸이 아님',
    'original_categories': 'Techmap occupation — 원 사이트 카테고리가 아님',
    'addresses': 'jsonLD.jobLocation.address.streetAddress', 'published_at': 'jsonLD.datePosted, 날짜만',
    'deadline_display_raw': '원문 마감 표시는 오지 않음 → 비움. Techmap 정리값 validThrough는 field_status에',
    'recruitment_status': 'Techmap이 주지 않음 → 비움', 'fetched_at': 'API 응답을 받은 시각(UTC)',
    'last_checked_at': '다시 확인하지 않음 → 수집 시각과 같음',
    'classification': '형식 규칙상 DB 조회만으로 만들지 않음 → 비움', 'field_status': '각 칸의 상태와 이유(JSON)',
    'job_id': '팀원 MySQL에 넣지 않은 공고 → 비움', 'source': 'Techmap source — 원 사이트 (jobkorea_kr 등)',
    'source_version': '처음 본 버전 = 1', 'content_hash': '본문(jsonLD.description) sha256',
    'responsibilities': SPLIT_NOTE, 'qualifications': SPLIT_NOTE, 'preferred_requirements': SPLIT_NOTE,
    'benefits': '분할기가 이 칸을 나누지 않음 → 비움. 원문은 JSON raw_description',
    'hiring_process': '분할기가 이 칸을 나누지 않음 → 비움. 원문은 JSON raw_description',
    'application_notes': '분할기가 이 칸을 나누지 않음 → 비움. 원문은 JSON raw_description'}
ID_PATTERNS = (r'GI_Read/(\d+)', r'rec_idx=(\d+)', r'/jobs/(\d+)', r'/view/(\d+)', r'currentJobId=(\d+)')


def source_id(url):
    for pattern in ID_PATTERNS:
        m = re.search(pattern, url or '')
        if m:
            return m.group(1)
    return ''


def iso_stamp(stamp):
    """'20261105T132545Z' -> '2026-11-05T13:25:45Z'."""
    m = re.fullmatch(r'(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z', stamp or '')
    return f'{m[1]}-{m[2]}-{m[3]}T{m[4]}:{m[5]}:{m[6]}Z' if m else ''


def find_raw(posting, items):
    if posting['url'] in items:
        return items[posting['url']]
    for item in items.values():          # Greenhouse rows come without a URL: match on the title
        if (item.get('title') or '').strip() == posting['title'].strip():
            return item
    return {}


# How the body arrived from Techmap (checked 2026-11-14 on the 10 picked postings)
BODY_STATE = {
    'full': ('전부 옴', '끝까지 왔고 줄 구조도 살아 있음'),
    'flat': ('줄바꿈 사라짐', '한 줄이 1,000자를 넘음 — 표가 한 줄로 펴져 원문 줄 구분이 없어짐'),
    'table': ('표 칸 구분이 사라짐', '잡코리아 표의 머리글(모집분야·담당업무·자격요건·모집인원)이 맨 앞 줄에 몰리고 '
              '내용은 그 뒤에 이어짐 — 내용은 다 있지만 어느 줄이 어느 칸인지 원문에서 구분 안 됨'),
    'image': ('원문 대신 요약', '이미지 공고 — 수집기가 본문 없음으로 표시, 자동 요약 + 항목 목록만 옴'),
}
FLAT_LINE = 1000
TABLE_HEAD = ('모집분야', '담당업무', '자격요건', '모집인원')


def body_state(posting, desc):
    lines = [line.strip() for line in (desc or '').splitlines() if line.strip()]
    if posting.get('body_status') == 'no_body' or not lines:
        return 'image'
    if max(len(line) for line in lines) > FLAT_LINE:
        return 'flat'
    head = ''.join(line for line in lines[:4] if len(line) <= 40).replace(' ', '')
    if sum(word in head for word in TABLE_HEAD) >= 3:
        return 'table'
    return 'full'


def row_for(posting, item):
    sections = posting['sections']
    desc = get(item, 'jsonLD.description') or item.get('description') or ''
    addr = get(item, 'jsonLD.jobLocation.address') or {}
    places = [x for x in (addr.get('streetAddress') if isinstance(addr, dict) else None,
                          get(item, 'jsonLD.jobLocation.name')) if x]
    occupation = item.get('occupation') or get(item, 'jsonLD.relevantOccupation')
    posted = (get(item, 'jsonLD.datePosted') or (posting.get('date_created') or ''))[:10]
    fetched = iso_stamp(posting.get('collected_at'))
    valid_through = get(item, 'jsonLD.validThrough') or item.get('dateExpired') or ''
    sid = source_id(posting['url'])
    state = body_state(posting, desc)
    absent = {'table': '표가 풀려 원문에서 칸 구분이 사라져 분할기가 못 나눔 — 내용은 JSON raw_description에 있음',
              'image': '이미지 공고 — 응답엔 자동 요약만 있어 이 내용이 없음'}.get(state)
    values, status = {}, {}

    def put(col, value, kind, note=''):
        values[col] = value
        status[col] = {'status': kind, **({'note': note} if note else {})}

    put('source_id', sid, 'computed' if sid else 'missing',
        'URL에서 추출' if sid else 'Techmap 응답에 원 공고 URL이 없어 ID를 알 수 없음')
    put('source_url', posting['url'], 'source' if posting['url'] else 'missing', '' if posting['url'] else 'URL 없음')
    put('title', posting['title'], 'source')
    put('company_name', posting['company'], 'source')
    skills = posting.get('provider_skills') or []
    put('tech_stacks', skills, 'techmap' if skills else 'missing',
        'Techmap 자동 기술 태그 (원 공고가 단 태그 아님, 표기가 다를 수 있음)' if skills else '태그 없음')
    put('original_categories', [occupation] if occupation else [], 'techmap' if occupation else 'missing',
        'Techmap occupation (원 사이트 카테고리 아님)' if occupation else '분류 없음')
    put('addresses', places, 'source' if places else 'missing', '' if places else '주소 없음')
    put('published_at', posted, 'source' if posted else 'missing', '날짜만 확인 — 시각을 붙이지 않음' if posted else '등록일 없음')
    put('deadline_display_raw', '', 'missing',
        f'원문 마감 표시는 오지 않음. Techmap 정리값 validThrough={valid_through}' if valid_through else '마감 정보 없음')
    put('recruitment_status', '', 'missing', 'Techmap은 모집 상태를 주지 않음 — 확인 전')
    put('fetched_at', fetched, 'computed', 'Techmap API 응답을 받은 시각(UTC)')
    put('last_checked_at', fetched, 'computed', '다시 확인하지 않아 수집 시각과 같음')
    put('classification', '', 'missing', '수집 비교 분류는 DB 조회만으로 만들지 않음 (형식 규칙)')
    put('job_id', '', 'missing', '팀원 MySQL에 들어가지 않은 공고라 내부 ID 없음')
    put('source', posting['source'], 'source', 'Techmap Jobs API 경유')
    put('source_version', 1, 'computed', '처음 본 버전')
    put('content_hash', hashlib.sha256(desc.encode('utf-8')).hexdigest() if desc else '', 'computed' if desc else 'missing',
        '본문(jsonLD.description) sha256' if desc else '본문 없음')
    for col, key in (('responsibilities', 'responsibilities'), ('qualifications', 'qualifications'),
                     ('preferred_requirements', 'preferred')):
        text = tidy(sections.get(key))
        put(col, text, 'derived' if text else 'missing',
            '본문 한 덩어리를 우리 분할기가 나눈 원문 줄 (요약 아님)' if text
            else absent or '분할기가 이 칸을 찾지 못함 — 원문은 JSON raw_description')
    for col in ('benefits', 'hiring_process', 'application_notes'):
        put(col, '', 'missing', absent or 'Techmap 본문이 한 덩어리라 이 칸은 나누지 않음 — 원문은 JSON raw_description')
    put('field_status', '', 'computed')
    status['_body'] = {'state': state, 'note': f'{BODY_STATE[state][0]}: {BODY_STATE[state][1]}'}
    leftover = tidy(sections.get('unknown'))
    if leftover:   # lines under no recognised heading (intro, 모집분야, ...): not in any column
        status['_unassigned'] = {'status': 'missing', 'note': f'어느 칸에도 넣지 않은 줄 {len(leftover)}자 '
                                 '(소제목 앞 소개·모집분야 등) — 원문은 JSON raw_description'}
    values['field_status'] = status
    return values, desc, posting['body_status']


def csv_cell(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return '' if value is None else str(value)


def build():
    items, _ = raw_items()
    postings = pick(json.loads(JOBS.read_text(encoding='utf-8'))['postings'])
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in postings:
        item = find_raw(p, items)
        values, desc, body = row_for(p, item)
        rows.append((p, values, desc, body, item))
    with (OUT / 'techmap_10_extract.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL, lineterminator='\r\n')
        writer.writerow(COLUMNS)
        for _, values, _, _, _ in rows:
            writer.writerow([csv_cell(values[c]) for c in COLUMNS])
    (OUT / 'techmap_10_extract.json').write_text(json.dumps(
        [{**{c: values[c] for c in COLUMNS}, 'raw_description': desc, 'techmap_raw': item}
         for _, values, desc, _, item in rows], ensure_ascii=False, indent=1), encoding='utf-8')
    (OUT / 'techmap_10_extract.html').write_text(render(rows), encoding='utf-8')
    return OUT


def render(rows):
    e = html.escape
    counts = {c: {k: 0 for k in STATUS} for c in COLUMNS}
    for _, values, _, _, _ in rows:
        for c in COLUMNS:
            counts[c][values['field_status'][c]['status']] += 1
    main_kind = {c: max(counts[c], key=counts[c].get) for c in COLUMNS}
    totals = {k: sum(counts[c][k] for c in COLUMNS) for k in STATUS}
    legend = ''.join(f"<span class='lg s-{k}'>{e(n)} <b>{totals[k]}</b></span>" for k, (n, _) in STATUS.items())
    legend_note = ''.join(f"<li><span class='chip s-{k}'>{e(n)}</span> {e(d)}</li>" for k, (n, d) in STATUS.items())
    map_rows = ''.join(
        f"<tr><td><code>{c}</code>{'<span class=ext>확장</span>' if c in EXTENDED else ''}</td><td>{e(MEANING[c])}</td>"
        f"<td><span class='chip s-{main_kind[c]}'>{e(STATUS[main_kind[c]][0])}</span></td>"
        f"<td>{e(COLUMN_NOTE[c])}</td>"
        f"<td>{len(rows) - counts[c]['missing']} / {len(rows)}</td></tr>" for c in COLUMNS)
    head = ''.join(f"<th title='{c}'><span>{i + 1}</span></th>" for i, c in enumerate(COLUMNS))
    key = ''.join(f"<span><b>{i + 1}</b> {c}</span>" for i, c in enumerate(COLUMNS))
    matrix = ''.join(
        f"<tr><td class='nm'>{e(p['company'])}</td>" + ''.join(
            f"<td><i class='dot s-{values['field_status'][c]['status']}' title='{c}: {e(STATUS[values['field_status'][c]['status']][0])}'></i></td>"
            for c in COLUMNS) + '</tr>' for p, values, _, _, _ in rows)
    long_cols = {'responsibilities', 'qualifications', 'preferred_requirements', 'field_status'}
    cards = []
    for p, values, desc, body, _ in rows:
        cells = []
        for c in COLUMNS:
            st = values['field_status'][c]
            v = values[c]
            shown = json.dumps(v, ensure_ascii=False, indent=1) if c == 'field_status' else csv_cell(v)
            note = f"<div class='note'>{e(st.get('note', ''))}</div>" if st.get('note') and c != 'field_status' else ''
            body_html = (f"<pre>{e(shown)}</pre>" if c in long_cols and shown else f"<div class='val'>{e(shown) or '<span class=empty>(비움)</span>'}</div>")
            cells.append(f"<div class='cell s-{st['status']}{' wide' if c in long_cols else ''}'><div class='cn'><code>{c}</code>"
                         f"<span class='chip s-{st['status']}'>{e(STATUS[st['status']][0])}</span></div>{body_html}{note}</div>")
        cards.append(f"<details class='card'><summary><b>{e(p['company'])}</b> · {e(re.sub(r'\s+', ' ', p['title']))}"
                     f"<span class='src'>{e(p['source'])}</span></summary><div class='grid'>{''.join(cells)}</div>"
                     f"<h4>참고: Techmap 원본 본문 (JSON의 raw_description, 앞부분)</h4><pre class='raw'>{e(tidy(desc)[:1200])}"
                     f"{'…' if len(desc) > 1200 else ''}</pre></details>")
    return PAGE.format(legend=legend, legend_note=legend_note, map_rows=map_rows, head=head, key=key,
                       matrix=matrix, cards=''.join(cards), n=len(rows))


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Techmap 공고 추출 형식 변환</title><style>
:root{{--bg:#fbfaf7;--card:#fff;--line:#e4e1d8;--text:#2c2c2a;--muted:#6b6a64;--accent:#185fa5;
--s-source:#3b6d11;--s-source-bg:#eaf3de;--s-techmap:#185fa5;--s-techmap-bg:#e6f1fb;--s-derived:#854f0b;--s-derived-bg:#faeeda;--s-computed:#534ab7;--s-computed-bg:#eeedfe;--s-missing:#888780;--s-missing-bg:#f1efe8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1f1f1d;--card:#2a2a28;--line:#3d3d3a;--text:#ecebe6;--muted:#a9a79f;--accent:#85b7eb;
--s-source:#c0dd97;--s-source-bg:#22330f;--s-techmap:#85b7eb;--s-techmap-bg:#0c2a45;--s-derived:#fac775;--s-derived-bg:#3d2a0a;--s-computed:#afa9ec;--s-computed-bg:#26215c;--s-missing:#b4b2a9;--s-missing-bg:#2c2c2a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 'Segoe UI',system-ui,-apple-system,'Malgun Gothic',sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:24px;margin:0 0 6px}}h2{{font-size:18px;margin:32px 0 10px}}h4{{font-size:13px;color:var(--muted);margin:14px 0 6px}}
p.lead{{color:var(--muted);margin:0 0 14px}}code{{font:12px ui-monospace,Consolas,monospace;color:var(--accent);word-break:break-all}}
.legend{{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}}.lg,.chip{{display:inline-block;border-radius:6px;padding:2px 9px;font-size:12px}}
.s-source{{--c:var(--s-source);--b:var(--s-source-bg)}}.s-techmap{{--c:var(--s-techmap);--b:var(--s-techmap-bg)}}.s-derived{{--c:var(--s-derived);--b:var(--s-derived-bg)}}.s-computed{{--c:var(--s-computed);--b:var(--s-computed-bg)}}.s-missing{{--c:var(--s-missing);--b:var(--s-missing-bg)}}
.lg,.chip{{color:var(--c);background:var(--b)}}ul.ln{{list-style:none;padding:0;margin:0;font-size:13px;color:var(--muted)}}ul.ln li{{margin:4px 0}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);font-size:13px}}th,td{{text-align:left;padding:6px 9px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{background:var(--bg);font-size:12px;color:var(--muted)}}.ext{{margin-left:6px;font-size:10px;color:var(--muted);border:1px solid var(--line);border-radius:4px;padding:0 4px}}
.mx{{overflow-x:auto}}.mx table{{width:auto}}.mx th,.mx td{{text-align:center;padding:5px 4px}}.mx td.nm{{text-align:left;white-space:nowrap;font-size:12px;padding-right:12px}}
.dot{{display:inline-block;width:16px;height:16px;border-radius:4px;background:var(--b);border:2px solid var(--c)}}.key{{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:11px;color:var(--muted);margin:8px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:0 0 10px;padding:12px 14px}}summary{{cursor:pointer;font-size:15px}}.src{{margin-left:8px;font-size:12px;color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:8px;margin-top:12px}}.cell{{border:1px solid var(--line);border-left:4px solid var(--c);border-radius:0 8px 8px 0;padding:7px 9px;background:var(--bg)}}
.cell.wide{{grid-column:1/-1}}.cn{{display:flex;justify-content:space-between;gap:6px;align-items:center;margin-bottom:4px}}.val{{font-size:13px;word-break:break-all}}.empty{{color:var(--muted)}}
.note{{font-size:11px;color:var(--muted);margin-top:4px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 'Segoe UI',system-ui,-apple-system,'Malgun Gothic',sans-serif;margin:0;padding:6px 8px;background:var(--card);border-radius:6px;max-height:340px;overflow:auto}}
</style></head><body><main>
<h1>Techmap 공고 → 팀원 추출 형식 변환 (10건)</h1>
<p class="lead">팀원의 "채용공고 추출 파일 형식"(기본 14 + 확장 10 = 24개 컬럼)에 맞춰, <b>이미 받아 둔 Techmap API 응답</b>을 변환했습니다(새 API 호출 없음). 같은 폴더의 <code>techmap_10_extract.csv</code>(UTF-8 BOM)와 <code>techmap_10_extract.json</code>(원본 본문·Techmap 원 응답 포함)이 같은 내용입니다. 원문이 들어 있어 팀 안에서만 봅니다.</p>
<div class="legend">{legend}</div><ul class="ln">{legend_note}</ul>

<h2>1. 한눈에: 공고 × 컬럼 상태</h2>
<div class="mx"><table><tr><th></th>{head}</tr>{matrix}</table></div><div class="key">{key}</div>

<h2>2. 컬럼별로 어디서 왔나</h2>
<table><tr><th>컬럼</th><th>뜻(형식 안내)</th><th>주된 상태</th><th>설명</th><th>채움</th></tr>{map_rows}</table>

<h2>3. 공고 {n}건 — 눌러서 24개 컬럼 전체 보기</h2>
{cards}
</main></body></html>"""


if __name__ == '__main__':
    print(build())
