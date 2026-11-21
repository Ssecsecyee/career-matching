"""Build a local HTML page that shows which Techmap fields arrive and what we keep.

    python -m eval.techmap_view      # -> data/real/techmap/fields_view.html (git-ignored: it quotes postings)

Techmap terms forbid redistributing posting text, so the page is written next to the raw data and
is not published anywhere.
"""
import glob
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'real' / 'techmap' / 'raw'
JOBS = ROOT / 'data' / 'real' / 'jobs.json'
OUT = ROOT / 'data' / 'real' / 'techmap' / 'fields_view.html'

# field path -> (group, meaning, our field or '' when not kept)
FIELDS = {
    'title': ('기본', '공고 제목', 'title'),
    'company': ('기본', '회사 이름(짧은 이름)', ''),
    'source': ('기본', '원 출처 사이트 (예: jobkorea_kr)', 'source'),
    'portal': ('기본', '원 출처 포털', 'portal'),
    'countryCode': ('기본', '국가', ''),
    'language': ('기본', '공고 언어', 'language'),
    'locale': ('기본', '지역 설정', ''),
    'occupation': ('분류', 'Techmap이 붙인 직종', ''),
    'industry': ('분류', '산업', ''),
    'skills': ('분류', 'Techmap이 자동으로 붙인 기술 태그 (공고 원문 표기와 다를 수 있음)', 'provider_skills'),
    'careerLevel': ('분류', '경력 수준', ''),
    'workType': ('분류', '근무 형태', ''),
    'contractType': ('분류', '계약 형태', ''),
    'department': ('분류', '부서', ''),
    'dateCreated': ('날짜', '등록일', 'date_created'),
    'dateActive': ('날짜', '유효 기한', ''),
    'dateExpired': ('날짜', '만료일', ''),
    'city': ('위치', '시', 'region'),
    'state': ('위치', '시·도', 'region (city 없을 때)'),
    'geoPoint': ('위치', '위도·경도', ''),
    'workPlace': ('위치', '근무지 유형', ''),
    'isDuplicate': ('표시', 'Techmap 중복 표시', ''),
    'isRecruiter': ('표시', '헤드헌터 공고 여부', ''),
    'isDirect': ('표시', '직접 지원 여부', ''),
    'hasSalary': ('표시', '급여 공개 여부', ''),
    'jsonLD.description': ('본문 (jsonLD)', '**공고 본문 전체** — 자격요건·우대·업무가 한 덩어리로 들어 있음', 'sections (우리 분할기로 나눔)'),
    'jsonLD.url': ('본문 (jsonLD)', '원 공고 주소', 'url'),
    'jsonLD.hiringOrganization.name': ('본문 (jsonLD)', '회사 정식 이름', 'company'),
    'jsonLD.experienceRequirements.description': ('본문 (jsonLD)', '경력 요건 (예: 경력 3~7년)', ''),
    'jsonLD.educationRequirements': ('본문 (jsonLD)', '학력 요건', ''),
    'jsonLD.employmentType': ('본문 (jsonLD)', '고용 형태', ''),
    'jsonLD.datePosted': ('본문 (jsonLD)', '게시일', ''),
    'jsonLD.validThrough': ('본문 (jsonLD)', '마감일', ''),
    'jsonLD.skills': ('본문 (jsonLD)', '기술 태그 (위 skills와 같음)', ''),
    'jsonLD.jobLocation.name': ('본문 (jsonLD)', '근무지 이름', ''),
}
OURS = [
    ('id', '공고 주소로 만든 고유 번호', '계산'),
    ('company', '회사 정식 이름', 'jsonLD.hiringOrganization.name (없으면 company)'),
    ('title', '제목', 'jsonLD.title (없으면 title)'),
    ('url', '원 공고 주소', 'jsonLD.url — 같은 주소는 한 번만'),
    ('source / portal / language', '출처·포털·언어', '그대로'),
    ('region', '지역', 'city (없으면 state)'),
    ('date_created', '등록일', 'dateCreated'),
    ('provider_skills', 'Techmap 기술 태그', 'skills — 정답·추출에는 쓰지 않고 사전 후보 찾기에만'),
    ('body_status', '본문 상태: 섹션 있음 / 섹션 없음 / 본문 없음(이미지)', 'description 길이와 섹션 제목으로 판정'),
    ('sections', '자격요건 · 우대사항 · 주요업무 · 구분없음', 'description을 우리 분할기(segment.py)로 나눔'),
    ('also_at', '다른 사이트에 실린 같은 공고', '중복 합치기(F-006)'),
]
SEC = [('qualifications', '자격요건', 'q'), ('preferred', '우대사항', 'p'),
       ('responsibilities', '주요업무', 'r'), ('unknown', '구분 없음', 'u')]
STATUS = {'has_sections': ('ok', '섹션 있음'), 'no_sections': ('mid', '섹션 없음'), 'no_body': ('bad', '본문 없음(이미지)')}


def get(item, path):
    cur = item
    for part in path.split('.'):
        if isinstance(cur, list):
            cur = cur[0] if cur else None
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def filled(v):
    return v not in (None, '', [], {}, 'N/A')


def tidy(text):
    """Collapse runs of blank lines so the source reads as paragraphs."""
    return re.sub(r'\n\s*\n+', '\n', (text or '').strip())


def show(v, n=60):
    if isinstance(v, list):
        v = ', '.join(str(x) if not isinstance(x, dict) else json.dumps(x, ensure_ascii=False) for x in v)
    elif isinstance(v, dict):
        v = json.dumps(v, ensure_ascii=False)
    s = re.sub(r'\s+', ' ', str(v))
    return s if len(s) <= n else s[:n] + '…'


def raw_items():
    items, calls = {}, []
    for f in sorted(glob.glob(str(RAW / '*.json'))):
        d = json.loads(Path(f).read_text(encoding='utf-8'))
        resp = d.get('response') or {}
        calls.append((d.get('collected_at'), d.get('endpoint'), resp.get('totalCount'), len(resp.get('result') or [])))
        for it in resp.get('result') or []:
            items[get(it, 'jsonLD.url') or it.get('url') or json.dumps(it)[:80]] = it
    return items, calls


def pick(postings):
    order = ['has_sections'] * 5 + ['no_sections'] * 3 + ['no_body'] * 2
    out = []
    for status in order:
        for p in postings:
            if p not in out and p['body_status'] == status and sum(1 for x in out if x['source'] == p['source']) < 5:
                out.append(p)
                break
    return out


def build():
    items, calls = raw_items()
    jobs = json.loads(JOBS.read_text(encoding='utf-8'))
    postings, ds = jobs['postings'], jobs['dataset']
    e = html.escape
    rows = []
    for path, (group, meaning, ours) in FIELDS.items():
        vals = [get(it, path) for it in items.values()]
        rate = sum(1 for v in vals if filled(v)) / len(vals) if vals else 0
        example = next((v for v in vals if filled(v)), '')
        rows.append(f"<tr><td><span class='grp'>{e(group)}</span></td><td><code>{e(path)}</code></td>"
                    f"<td>{e(meaning).replace('**', '')}</td><td><div class='rate'><i style='width:{rate*100:.0f}%'></i></div>"
                    f"<small>{rate:.0%}</small></td><td class='ex'>{e(show(example))}</td>"
                    f"<td>{('<span class=keep>' + e(ours) + '</span>') if ours else '<span class=drop>안 씀</span>'}</td></tr>")
    ours_rows = ''.join(f"<tr><td><code>{e(a)}</code></td><td>{e(b)}</td><td>{e(c)}</td></tr>" for a, b, c in OURS)
    cards = []
    for p in pick(postings):
        it = items.get(p['url'], {})
        cls, lab = STATUS[p['body_status']]
        desc = get(it, 'jsonLD.description') or ''
        sec_len = {k: len(p['sections'].get(k) or '') for k, _, _ in SEC}
        bars = ''.join(f"<div class='seg {c}' style='flex:{max(sec_len[k], 0)}' title='{n} {sec_len[k]}자'></div>"
                       for k, n, c in SEC if sec_len[k])
        legend = ' '.join(f"<span class='lg {c}'>{n} {sec_len[k]}자</span>" for k, n, c in SEC if sec_len[k])
        blocks = ''.join(f"<div class='blk {c}'><b>{n}</b><pre>{e(tidy(p['sections'].get(k))[:700])}"
                         f"{'…' if len(p['sections'].get(k) or '') > 700 else ''}</pre></div>"
                         for k, n, c in SEC if p['sections'].get(k))
        tags = ''.join(f"<span class='tag'>{e(s)}</span>" for s in p.get('provider_skills') or []) or "<span class='drop'>태그 없음</span>"
        meta = [('출처', p['source']), ('경력', show(get(it, 'jsonLD.experienceRequirements.description') or '미기재')),
                ('학력', show(get(it, 'jsonLD.educationRequirements') or '미기재')), ('게시', (get(it, 'jsonLD.datePosted') or p['date_created'] or '')[:10]),
                ('마감', (get(it, 'jsonLD.validThrough') or '')[:10] or '미기재'), ('본문 길이', f"{len(desc):,}자")]
        cards.append(f"""<details class='card'><summary><div class='ct'>{e(p['company'])} · {e(re.sub(r'\s+', ' ', p['title']))}</div>
<div class='meta'><span class='st {cls}'>{lab}</span>{''.join(f"<span><em>{e(a)}</em> {e(str(b))}</span>" for a, b in meta)}</div>
<div class='tags'>{tags}</div><div class='bar'>{bars}</div><div class='legend'>{legend}</div></summary>
<div class='body'><h4>Techmap 원본 본문 (jsonLD.description, 앞부분)</h4><pre class='raw'>{e(tidy(desc)[:900])}{'…' if len(desc) > 900 else ''}</pre>
<h4>우리 분할기가 나눈 결과 (sections)</h4>{blocks}</div></details>""")
    call_rows = ''.join(f"<tr><td>{e(str(a))}</td><td>{e(str(b))}</td><td>{e(str(c))}</td><td>{d}</td></tr>" for a, b, c, d in calls)
    received = sum(n for _, endpoint, _, n in calls if str(endpoint).startswith('search'))
    page = TEMPLATE.format(received=received, n_raw=len(items), n_post=ds['postings'], dup=ds.get('duplicates_dropped', 0),
                           merged=ds.get('cross_source_merged', 0), bs=ds['body_status'],
                           readable=ds['body_status'].get('has_sections', 0) + ds['body_status'].get('no_sections', 0),
                           field_rows=''.join(rows), ours_rows=ours_rows, cards=''.join(cards), call_rows=call_rows,
                           n_fields=len(FIELDS), n_kept=sum(1 for v in FIELDS.values() if v[2]))
    OUT.write_text(page, encoding='utf-8')
    return OUT


TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Techmap 공고 필드 보기</title><style>
:root{{--bg:#fbfaf7;--card:#fff;--line:#e4e1d8;--text:#2c2c2a;--muted:#6b6a64;--accent:#185fa5;--accbg:#e6f1fb;--ok:#3b6d11;--okbg:#eaf3de;--mid:#854f0b;--midbg:#faeeda;--bad:#a32d2d;--badbg:#fcebeb;--q:#378add;--p:#639922;--r:#ba7517;--u:#b4b2a9}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#1f1f1d;--card:#2a2a28;--line:#3d3d3a;--text:#ecebe6;--muted:#a9a79f;--accent:#85b7eb;--accbg:#0c2a45;--ok:#c0dd97;--okbg:#22330f;--mid:#fac775;--midbg:#3d2a0a;--bad:#f7c1c1;--badbg:#4a1b1b;--u:#6b6a64}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 system-ui,-apple-system,'Segoe UI','Malgun Gothic',sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:24px;font-weight:600;margin:0 0 6px}}h2{{font-size:18px;font-weight:600;margin:34px 0 10px}}
h4{{font-size:13px;margin:14px 0 6px;color:var(--muted);font-weight:600}}p.lead{{color:var(--muted);margin:0 0 18px}}
.flow{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}.flow div{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}}
.flow b{{display:block;font-size:20px}}.flow small{{color:var(--muted)}}.flow .arr{{border:0;background:none;padding:0;color:var(--muted)}}
table{{width:100%;table-layout:fixed;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}}th{{background:var(--bg);font-weight:600;font-size:12px;color:var(--muted)}}
code{{font:12px ui-monospace,Consolas,monospace;color:var(--accent)}}.grp{{font-size:11px;color:var(--muted)}}td.ex{{color:var(--muted);font-size:12px;word-break:break-all}}code{{word-break:break-all}}
.rate{{width:70px;height:6px;background:var(--line);border-radius:3px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:6px}}.rate i{{display:block;height:100%;background:var(--accent)}}
.keep{{background:var(--accbg);color:var(--accent);padding:1px 7px;border-radius:6px;font-size:12px;white-space:nowrap}}.drop{{color:var(--muted);font-size:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin:0 0 10px;padding:12px 14px}}summary{{cursor:pointer;list-style:none}}summary::-webkit-details-marker{{display:none}}
.ct{{font-weight:600;font-size:15px}}.meta{{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted);margin:6px 0}}.meta em{{font-style:normal;color:var(--text);opacity:.6}}
.st{{padding:1px 8px;border-radius:6px;font-weight:600}}.ok{{background:var(--okbg);color:var(--ok)}}.mid{{background:var(--midbg);color:var(--mid)}}.bad{{background:var(--badbg);color:var(--bad)}}
.tags{{display:flex;flex-wrap:wrap;gap:4px;margin:4px 0}}.tag{{font-size:11px;border:1px solid var(--line);border-radius:5px;padding:0 6px;color:var(--muted)}}
.bar{{display:flex;height:10px;border-radius:5px;overflow:hidden;margin:8px 0 4px;background:var(--line)}}.seg.q{{background:var(--q)}}.seg.p{{background:var(--p)}}.seg.r{{background:var(--r)}}.seg.u{{background:var(--u)}}
.legend{{font-size:11px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap}}.lg::before{{content:'';display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:4px;vertical-align:middle}}
.lg.q::before{{background:var(--q)}}.lg.p::before{{background:var(--p)}}.lg.r::before{{background:var(--r)}}.lg.u::before{{background:var(--u)}}
.body{{border-top:1px dashed var(--line);margin-top:10px}}pre{{white-space:pre-wrap;word-break:keep-all;overflow-wrap:anywhere;font:13px/1.6 system-ui,-apple-system,'Segoe UI','Malgun Gothic',sans-serif;margin:0;padding:8px 10px;background:var(--bg);border-radius:8px}}
.blk{{border-left:4px solid var(--u);border-radius:0;margin:6px 0;padding-left:8px}}.blk b{{font-size:12px}}.blk.q{{border-color:var(--q)}}.blk.p{{border-color:var(--p)}}.blk.r{{border-color:var(--r)}}
.note{{font-size:13px;color:var(--muted)}}.note li{{margin:4px 0}}.hint{{font-size:12px;color:var(--muted);margin:-4px 0 10px}}
</style></head><body><main>
<h1>Techmap 공고 필드 보기</h1>
<p class="lead">Techmap Jobs API(RapidAPI)로 받은 한국 백엔드 공고에서 <b>어떤 칸에 어떤 정보가 오는지</b>, 그중 <b>무엇을 골라 어떻게 바꿨는지</b>를 보여 줍니다. 원문을 담고 있어 이 파일은 로컬에만 둡니다(재배포 금지 약관).</p>
<div class="flow"><div><b>{received}</b><small>받은 공고 (검색 페이지 × 10건)</small></div><span class="arr">→</span>
<div><b>{n_raw}</b><small>같은 주소 {dup}건 제외</small></div><span class="arr">→</span>
<div><b>{n_post}</b><small>사이트 간 같은 공고 {merged}쌍 합침</small></div><span class="arr">→</span>
<div><b>{readable}</b><small>글을 읽을 수 있는 공고 (본문 없음 {bs[no_body]} 제외)</small></div><span class="arr">→</span>
<div><b>22</b><small>연습용 정답셋 (사람 승인)</small></div></div>

<h2>1. Techmap이 주는 필드 ({n_fields}개 중 {n_kept}개 사용)</h2>
<p class="hint">채움 비율 = 받은 공고 중 그 칸에 값이 있는 비율. 예시는 실제 값의 앞부분.</p>
<table><colgroup><col style="width:9%"><col style="width:22%"><col style="width:24%"><col style="width:12%"><col style="width:19%"><col style="width:14%"></colgroup>
<tr><th>묶음</th><th>필드</th><th>뜻</th><th>채움</th><th>예시 값</th><th>우리가 쓰는 곳</th></tr>{field_rows}</table>

<h2>2. 우리 형식으로 바꾼 결과</h2>
<table><tr><th>우리 필드</th><th>뜻</th><th>어디서 오나</th></tr>{ours_rows}</table>

<h2>3. 공고 10건 — 눌러서 원문과 분할 결과 보기</h2>
<p class="hint">막대 = 우리 분할기가 나눈 칸별 글자 수. 파랑 자격요건 · 초록 우대 · 주황 주요업무 · 회색 구분 없음.</p>
{cards}

<h2>4. 실제로 한 호출 (원본 그대로 data/real/techmap/raw/)</h2>
<table><tr><th>시각(UTC)</th><th>요청</th><th>조건에 맞는 전체 건수</th><th>받은 건수</th></tr>{call_rows}</table>

<h2>5. 보면서 알 수 있는 것</h2><ul class="note">
<li><b>본문은 한 칸에 통째로</b> 온다(<code>jsonLD.description</code>). 자격요건·우대 구분은 우리 분할기가 만든다 — 사람인 공고는 잘 나뉘고, 제목 없는 공고는 "구분 없음"으로 몰린다(실패 노트 F-010).</li>
<li><b>기술 태그 <code>skills</code>는 Techmap이 자동으로 붙인 것</b>이라 공고 표기와 다르다("Spring Framework", "PL / SQL"). 그래서 정답셋은 태그가 아니라 본문에 적힌 것을 기준으로 했다.</li>
<li><b>본문 없음</b> 공고는 본문이 이미지라 Techmap이 "○○에서 채용을 진행합니다" 같은 틀 문장만 준다 → 분석 제외.</li>
<li>경력·학력·마감일은 정리된 칸으로 따로 온다 — 공고 걸러 내기에 쓸 수 있다.</li></ul>
</main></body></html>"""


if __name__ == '__main__':
    print(build())
