"""Small versioned spelling expansions, shared by both search backends."""
POLICY_VERSION = 'structured-search-v4'
REGIONS = {'경남': ('경남', '경상남도'), '경상남도': ('경남', '경상남도'),
           '부산': ('부산',), '부산광역시': ('부산',)}
for short,long in [('충북','충청북도'),('충남','충청남도'),('전북','전라북도'),('전남','전라남도'),('경북','경상북도'),('제주','제주특별자치도'),('강원','강원특별자치도')]:
    REGIONS[short]=(short,long);REGIONS[long]=(short,long)
REGIONS['전북']=('전북','전라북도','전북특별자치도')
REGIONS['강원']=('강원','강원도','강원특별자치도')
for variants in [('서울','서울특별시'),('경기','경기도'),('인천','인천광역시'),('부산','부산광역시'),('대구','대구광역시'),('대전','대전광역시'),('광주','광주광역시'),('울산','울산광역시'),('세종','세종특별자치시'),('경남','경상남도'),('전북','전라북도','전북특별자치도'),('강원','강원도','강원특별자치도')]:
    for variant in variants:REGIONS[variant]=variants
VUE_SPELLINGS = ('Vue', 'Vue.js', 'VueJs')
SKILLS = {'vue': VUE_SPELLINGS, 'vuejs': VUE_SPELLINGS, 'vue.js': VUE_SPELLINGS,
          'react.js': ('React', 'React.js'), 'react': ('React', 'React.js'),
          '리액트': ('React', 'React.js'), '리엑트': ('React', 'React.js'),
          'python': ('Python',), '파이썬': ('Python',),
          'angular': ('Angular', 'Angular 2'), 'c/c++': ('C', 'C++')}
SKILLS.update({'git':('Git',),'깃':('Git',),'깃허브':('GitHub',),'github':('GitHub',),'자바':('Java',),'도커':('Docker',),'타입스크립트':('TypeScript',)})
ROLES = {'백엔드': ('백엔드', 'backend', '서버 개발'),
         '프론트엔드': ('프론트엔드', 'frontend', '프론트 엔드'),
         '데이터 엔지니어링': ('데이터 엔지니어', 'data engineer', '데이터 파이프라인', '데이터수집', '데이터 수집'),
         '데이터 엔지니어': ('데이터 엔지니어', 'data engineer', '데이터 파이프라인', '데이터수집', '데이터 수집')}


def skill_terms(term):
    return SKILLS.get(term.casefold(), (term,))


def region_terms(terms):
    return tuple(dict.fromkeys(t for term in terms for t in REGIONS.get(term, (term,))))


def role_terms(terms):
    return tuple(dict.fromkeys(t for term in terms for t in ROLES.get(term, (term,))))


def matches_skill(stacks, term):
    values = {v.casefold() for v in stacks}
    return any(v.casefold() in values for v in skill_terms(term))


def normalize_search_plan(plan):
    from src.schemas.search import SearchPlan
    data=plan.to_dict()
    if plan.schema_version==2:
        data['regions']=list(dict.fromkeys(REGIONS.get(v,(v,))[0] for v in plan.regions))
        for key in ('owned_skills','required_skills','preferred_skills'):
            data[key]=list(dict.fromkeys(term for v in getattr(plan,key) for term in (skill_terms(v) if v.casefold()=='c/c++' else (skill_terms(v)[0],))))
        data['text_query']=' '.join(skill_terms(v)[0] for v in plan.text_query.split())
    else:
        data['region']=REGIONS.get(plan.region,(plan.region,))[0]
        data['skills']=list(dict.fromkeys(term for v in plan.skills for term in (skill_terms(v) if v.casefold()=='c/c++' else (skill_terms(v)[0],))))
        data['keyword']=' '.join(skill_terms(v)[0] for v in plan.keyword.split())
    return SearchPlan.parse(data)
