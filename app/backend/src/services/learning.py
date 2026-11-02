"""Technology aliases for source display and education result attachment; no intent inference."""
import re

ALIASES={
 'ROS 2':['ros 2','ros2','로스2'],
 '센서 보정':['extrinsic calibration','센서 보정','외부 파라미터 보정'],
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

def attach(result,retrieval):
    if retrieval is None:return
    result['learning_opportunities']=retrieval['courses']
    result['learning_search']={k:v for k,v in retrieval.items() if k!='courses'}
