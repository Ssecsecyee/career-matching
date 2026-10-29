"""Connect explicit learning requests to technical gaps and sourced education facts."""
import re
from copy import deepcopy

ALIASES={
 'UI/UX':['ui/ux','ui ux','uiux','ui 디자인','ux 디자인','ui/ux 디자인','사용자 경험 디자인'],
 'Figma':['figma','피그마'],
 'React':['react','리액트','리엑트'], 'Git':['git','깃'], 'JavaScript':['javascript','자바스크립트'],
 'TypeScript':['typescript','타입스크립트'], 'Python':['python','파이썬'],
 'RAG':['rag','검색 증강'], 'LLM':['llm','대규모 언어 모델'],
 'AI Agent':['ai agent','ai 에이전트','ai에이전트'], 'MLOps':['mlops'],
 'LangGraph':['langgraph'], '머신러닝':['머신러닝','machine learning'],
 '딥러닝':['딥러닝','deep learning'], 'AWS':['aws','아마존웹서비스'],
 'Docker':['docker','도커'], 'Linux':['linux','리눅스'],
 'Java':['java','자바'], 'Spring':['spring','스프링'], 'Next.js':['next.js','nextjs'],
 'SQL':['sql'], 'MySQL':['mysql'], 'PostgreSQL':['postgresql','포스트그레'],
 'C++':['c++'], 'TensorFlow':['tensorflow','텐서플로'], 'PyTorch':['pytorch','파이토치'],
 '데이터 시각화':['데이터 시각화','데이터시각화'], '프론트엔드':['프론트엔드','frontend'],
 '백엔드':['백엔드','backend'], '풀스택':['풀스택','fullstack']}

def topics_in(text):
    return [topic for topic,aliases in ALIASES.items() if any(
        re.search(r'(?<![a-z0-9])'+re.escape(alias)+r'(?![a-z0-9])',text,re.I) for alias in aliases)]

def requested(message):
    return any(word in message.casefold() for word in ('학습','공부','교육','부트캠프','부트텐트','강의','수강','내일배움','국비','로드맵','배우','배워','배울','훈련 과정'))

def retrieve(state,message,repository):
    previous=state.get('learning_context')
    # A new explicit job request takes precedence over the previous education list.
    job_search=bool(re.search(r'(공고|채용|일자리|구인|구직).{0,16}(찾|검색|있|보여)',message))
    job_reference=bool(re.search(r'(공고|채용|일자리|구인|구직|회사|기업)',message)) and not requested(message)
    if job_search or job_reference:return None
    pending_topic=bool(previous) and previous.get('status')=='need_topic' and 0<len(message.strip())<=80 and message.strip() not in {'안녕','안녕하세요','고마워','감사합니다'}
    followup=pending_topic or (bool(previous) and (bool(re.search(r'(?:이|그)\s*중',message)) or any(word in message for word in (
        '이 과정','저 과정','첫 번째','두 번째','온라인','오프라인','수강료','비용','교육 기간',
        '추천','비교','어떤','어느','뭘','뭐가','제일','가장','더 나은'))))
    if repository is None or not (requested(message) or followup):return None
    explicit=topics_in(message)
    if followup and previous.get('courses') and (not explicit or set(explicit).issubset(previous.get('topics',[]))):
        # Compare the exact displayed snapshot, retaining order and source versions.
        result=deepcopy(previous)
        result['reference_resolution']='previously_displayed_training_courses'
        return result
    gaps=[]
    for kind in ('required','preferred'):
        for check in state.get('checks',[]):
            if check.get('type')==kind and check.get('assessment')=='unmet':
                gaps.extend(topics_in(check.get('quote','')))
    topics=list(dict.fromkeys(explicit+(previous.get('topics',[]) if followup and not explicit else [])+gaps))[:8]
    basis='explicit_learning_topic_and_self_assessed_gaps'
    if not topics:
        # Original user text only; model summaries and unknown checklist answers are not deficits.
        statements=state.get('profile',{}).get('memory',{}).get('user_statements',[])
        topics=list(dict.fromkeys(topic for item in reversed(statements[-6:]) for topic in topics_in(item.get('text',''))))[:8]
        basis='user_mentioned_topics_not_verified_deficits'
    courses=repository.search(topics) if topics else []
    return {'status':'found' if courses else ('no_match' if topics else 'need_topic'),
            'topics':topics,'basis':basis,'courses':courses,
            'limitations':['현재 모집 여부와 지원 자격을 실시간 확인한 결과가 아닙니다.',
                            '과거·미검증 과정은 학습 내용 참고용이며 신청 가능한 과정으로 추천하지 않습니다.',
                            '경력 연수·학위·실무 경험은 교육 수료로 대체할 수 없습니다.']}

def attach(result,retrieval):
    if retrieval is None:return
    result['learning_opportunities']=retrieval['courses']
    result['learning_search']={k:v for k,v in retrieval.items() if k!='courses'}
