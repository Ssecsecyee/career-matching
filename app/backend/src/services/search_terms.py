"""Small versioned spelling expansions, shared by both search backends."""
POLICY_VERSION = 'structured-search-v3'
REGIONS = {'경남': ('경남', '경상남도'), '경상남도': ('경남', '경상남도'),
           '부산': ('부산',), '부산광역시': ('부산',)}
for short,long in [('충북','충청북도'),('충남','충청남도'),('전북','전라북도'),('전남','전라남도'),('경북','경상북도'),('제주','제주특별자치도'),('강원','강원특별자치도')]:
    REGIONS[short]=(short,long);REGIONS[long]=(short,long)
REGIONS['전북']=('전북','전라북도','전북특별자치도')
REGIONS['강원']=('강원','강원도','강원특별자치도')
VUE_SPELLINGS = ('Vue', 'Vue.js', 'VueJs')
SKILLS = {'vue': VUE_SPELLINGS, 'vuejs': VUE_SPELLINGS, 'vue.js': VUE_SPELLINGS,
          'react.js': ('React', 'React.js'), 'react': ('React', 'React.js'),
          '리액트': ('React', 'React.js'), '리엑트': ('React', 'React.js'),
          'python': ('Python',), '파이썬': ('Python',),
          'angular': ('Angular', 'Angular 2'), 'c/c++': ('C', 'C++')}
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
