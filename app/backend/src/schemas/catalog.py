from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,StrictStr

JOB_FIELDS={'all':None,'title':'title','company_name':'company_name','responsibilities':'responsibilities','qualifications':'qualifications','preferred_requirements':'preferred_requirements','tech_stacks':'skills_text'}
TRAINING_FIELDS={'all':None,'title':'title','provider_name':'provider_name','curriculum':'curriculum','learning_topics':'learning_topics'}
class TrainingCatalogFilters(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    keyword:StrictStr=Field(default='',max_length=120)
    field:Literal['all','title','provider_name','curriculum','learning_topics','ncs_code']='all'
    region:StrictStr=Field(default='',max_length=80)
    delivery_mode:Literal['any','online','offline','unknown']='any'
    service:Literal['any','card','employer','consortium','work_study','boottent']='any'

def training_clauses(value):
    from src.repositories.mysql_jobs import literal_like
    filters=TrainingCatalogFilters.model_validate(value)
    clauses=[];params=[]
    columns={'title':'title','provider_name':'provider_name','curriculum':'curriculum','learning_topics':'CAST(learning_topics AS CHAR CHARACTER SET utf8mb4)','ncs_code':"JSON_UNQUOTE(JSON_EXTRACT(additional_sections,'$.collection_metadata.ncs_code'))"}
    if filters.keyword.strip():
        expression=columns.get(filters.field) or "CONCAT_WS(' ',title,provider_name,curriculum,eligibility,CAST(learning_topics AS CHAR CHARACTER SET utf8mb4),CAST(tech_stacks AS CHAR CHARACTER SET utf8mb4))"
        clauses.append('LOWER('+expression+") COLLATE utf8mb4_0900_ai_ci LIKE LOWER(%s) COLLATE utf8mb4_0900_ai_ci ESCAPE '='");params.append(literal_like(filters.keyword.strip()))
    if filters.region:
        from src.services.search_terms import region_terms
        terms=region_terms([filters.region])
        clauses.append('('+' OR '.join(["CAST(addresses AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_0900_ai_ci LIKE %s COLLATE utf8mb4_0900_ai_ci ESCAPE '='"]*len(terms))+')');params.extend(literal_like(t) for t in terms)
    if filters.delivery_mode=='unknown':clauses.append("COALESCE(delivery_mode,'unknown') NOT IN ('online','offline')")
    if filters.service=='boottent':
        clauses.append('source=%s');params.append('boottent')
    elif filters.service!='any':
        clauses.append('source=%s AND source_id LIKE %s');params+=['goyong24_training',filters.service+':%']
    return clauses,params
