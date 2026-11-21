"""Show the Techmap body text exactly as received, grouped by how it arrived — no new API call.

    python -m eval.techmap_raw_view   # -> data/real/techmap/export/techmap_10_raw_by_state.html (git-ignored)

Each posting's jsonLD.description is shown line by line, unchanged, with line numbers. Marks only point
at things: headings our splitter (segment.py) recognises, very long lines, and a trailing [label] line (not a cut-off).
"""
import html
import json
import re

from eval.techmap_export import BODY_STATE, JOBS, OUT, body_state, find_raw
from eval.techmap_view import get, pick, raw_items
from skillpath.segment import heading, normalize

SECTION_KO = {'qualifications': '자격요건', 'preferred': '우대사항', 'responsibilities': '주요업무',
              'drop': '버림(근무조건·복지 등)', 'unknown': '구분없음(모집분야 등)'}
LONG_LINE = 300


def line_marks(line, is_last, state):
    marks = []
    found = [h for h in (heading(sub) for sub in normalize(line).split('\n')) if h]
    for name in dict.fromkeys(found):
        marks.append(('h', f'분할기 소제목 → {SECTION_KO[name]}'))
    if len(line) > LONG_LINE:
        marks.append(('long', f'한 줄 {len(line):,}자'))
    if is_last and re.fullmatch(r'\s*\[[^\]]{2,40}\]\s*', line):
        marks.append(('tail', '끝에 붙은 꼬리표 줄 — 본문이 잘린 것 아님'))
    return marks


def posting_html(p, desc, state, open_):
    e = html.escape
    lines = desc.splitlines()
    nonblank = [i for i, line in enumerate(lines) if line.strip()]
    last = nonblank[-1] if nonblank else -1
    rows = []
    for i, line in enumerate(lines):
        marks = line_marks(line, i == last, state) if line.strip() else []
        chips = ''.join(f"<span class='mk mk-{k}'>{e(t)}</span>" for k, t in marks)
        cls = ' '.join(['ln'] + [f'is-{k}' for k, _ in marks])
        rows.append(f"<div class='{cls}'><span class='no'>{i + 1}</span><span class='tx'>{e(line) or '&nbsp;'}{chips}</span></div>")
    longest = max((len(line) for line in lines), default=0)
    link = (f"<a href='{e(p['url'])}' target='_blank' rel='noopener noreferrer'>원 공고 페이지 열기 ↗</a>"
            if p['url'] else "<span class='muted'>원 공고 URL 없음</span>")
    return (f"<details class='post'{' open' if open_ else ''}><summary><b>{e(p['company'])}</b> · "
            f"{e(re.sub(r'\s+', ' ', p['title']))}<span class='src'>{e(p['source'])}</span></summary>"
            f"<div class='meta'><span>{len(desc):,}자</span><span>{len(lines)}줄 (빈 줄 포함)</span>"
            f"<span>가장 긴 줄 {longest:,}자</span>{link}</div><div class='body'>{''.join(rows)}</div></details>")


def build():
    items, _ = raw_items()
    postings = pick(json.loads(JOBS.read_text(encoding='utf-8'))['postings'])
    groups = {k: [] for k in BODY_STATE}
    for p in postings:
        desc = get(find_raw(p, items), 'jsonLD.description') or ''
        groups[body_state(p, desc)].append((p, desc))
    e = html.escape
    overview = ''.join(
        f"<a class='st st-{k}' href='#{k}'><span class='stn'>{e(name)}</span><b>{len(groups[k])}건</b>"
        f"<span class='str'>{e(rule)}</span><span class='stc'>{e(', '.join(p['company'] for p, _ in groups[k]) or '없음')}</span></a>"
        for k, (name, rule) in BODY_STATE.items())
    sections = ''.join(
        f"<section id='{k}' class='st-{k}'><h2><span class='bar'></span>{e(name)} · {len(groups[k])}건</h2>"
        f"<p class='rule'>판정: {e(rule)}</p>"
        + ''.join(posting_html(p, d, k, i == 0) for i, (p, d) in enumerate(groups[k])) + '</section>'
        for k, (name, rule) in BODY_STATE.items() if groups[k])
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / 'techmap_10_raw_by_state.html'
    path.write_text(PAGE.format(overview=overview, sections=sections, n=len(postings), long=LONG_LINE), encoding='utf-8')
    return path


PAGE = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Techmap 본문 상태별 원문</title><style>
:root{{--bg:#fbfaf7;--card:#fff;--line:#e4e1d8;--text:#2c2c2a;--muted:#6b6a64;--accent:#185fa5;--hl:#fff3c4;
--full:#3b6d11;--full-bg:#eaf3de;--flat:#854f0b;--flat-bg:#faeeda;--table:#a32d2d;--table-bg:#fcebeb;--image:#534ab7;--image-bg:#eeedfe;--h:#185fa5;--h-bg:#e6f1fb}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1f1f1d;--card:#2a2a28;--line:#3d3d3a;--text:#ecebe6;--muted:#a9a79f;--accent:#85b7eb;--hl:#3d3410;
--full:#c0dd97;--full-bg:#22330f;--flat:#fac775;--flat-bg:#3d2a0a;--table:#f09595;--table-bg:#4a1b1b;--image:#afa9ec;--image-bg:#26215c;--h:#85b7eb;--h-bg:#0c2a45}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.6 'Segoe UI',system-ui,-apple-system,'Malgun Gothic',sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:28px 16px 60px}}h1{{font-size:24px;margin:0 0 6px}}p.lead{{color:var(--muted);margin:0 0 16px}}
code{{font:12px ui-monospace,Consolas,monospace;color:var(--accent)}}a{{color:var(--accent)}}.muted{{color:var(--muted)}}
.st-full{{--c:var(--full);--b:var(--full-bg)}}.st-flat{{--c:var(--flat);--b:var(--flat-bg)}}.st-table{{--c:var(--table);--b:var(--table-bg)}}.st-image{{--c:var(--image);--b:var(--image-bg)}}
.over{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px;margin:0 0 8px}}
.st{{display:flex;flex-direction:column;gap:3px;text-decoration:none;color:var(--text);background:var(--card);border:1px solid var(--line);border-top:4px solid var(--c);border-radius:10px;padding:10px 12px}}
.st .stn{{color:var(--c);font-weight:600}}.st b{{font-size:22px}}.st .str{{font-size:12px;color:var(--muted)}}.st .stc{{font-size:12px}}
h2{{font-size:18px;margin:34px 0 4px;display:flex;align-items:center;gap:8px}}.bar{{width:6px;height:20px;border-radius:3px;background:var(--c)}}p.rule{{margin:0 0 10px;color:var(--muted);font-size:13px}}
.post{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--c);border-radius:0 10px 10px 0;margin:0 0 10px;padding:10px 12px}}
summary{{cursor:pointer}}.src{{margin-left:8px;font-size:12px;color:var(--muted)}}.meta{{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--muted);margin:8px 0}}
.body{{border:1px solid var(--line);border-radius:8px;max-height:620px;overflow:auto;background:var(--bg)}}
.ln{{display:grid;grid-template-columns:3.2em 1fr;border-bottom:1px solid var(--line)}}.ln:last-child{{border-bottom:0}}
.no{{text-align:right;padding:2px 8px 2px 0;color:var(--muted);font:11px/1.9 ui-monospace,Consolas,monospace;user-select:none;border-right:1px solid var(--line)}}
.tx{{padding:2px 10px;white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px;line-height:1.65}}
.ln.is-h{{background:var(--h-bg)}}.ln.is-long .tx{{background:var(--flat-bg)}}.ln.is-tail .tx{{color:var(--muted)}}
.mk{{display:inline-block;margin-left:8px;font-size:11px;border-radius:5px;padding:0 6px;vertical-align:1px;white-space:nowrap}}
.mk-h{{color:var(--h);border:1px solid var(--h)}}.mk-long{{color:var(--flat);border:1px solid var(--flat)}}.mk-tail{{color:var(--muted);border:1px dashed var(--muted)}}
.legend{{font-size:12px;color:var(--muted);display:flex;flex-wrap:wrap;gap:6px 16px;margin:6px 0 0}}.legend i{{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-1px;margin-right:4px}}
</style></head><body><main>
<h1>Techmap 본문 — 상태별 원문 {n}건</h1>
<p class="lead">Techmap API가 준 본문(<code>jsonLD.description</code>)을 <b>한 글자도 고치지 않고</b> 줄 번호만 붙여 보여줍니다. <code>**</code>, <code>\\[</code>, <code>|---|</code> 같은 기호도 받은 그대로입니다. 새 API 호출 없음 · 원문 포함이라 팀 안에서만 봅니다.</p>
<div class="over">{overview}</div>
<div class="legend"><span><i style="background:var(--h-bg);border:1px solid var(--h)"></i>우리 분할기가 소제목으로 알아본 줄</span><span><i style="background:var(--flat-bg);border:1px solid var(--flat)"></i>{long}자 넘는 긴 줄</span><span><i style="border:1px dashed var(--muted)"></i>끝에 붙은 [꼬리표] 줄</span><span>각 상태의 첫 공고는 펼쳐 둠 · 나머지는 눌러서 열기</span></div>
{sections}
</main></body></html>"""


if __name__ == '__main__':
    print(build())
