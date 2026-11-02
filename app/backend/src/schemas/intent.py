"""Application-owned context routing contract. No executable DSL or arbitrary keys."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from src.schemas.search import SearchPlan, CareerPreference, Terms

INTENT_VERSION = 'context-intent-v1'

class SearchChanges(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    regions: Terms | None = None
    roles: Terms | None = None
    owned_skills: Terms | None = None
    required_skills: Terms | None = None
    preferred_skills: Terms | None = None
    career: CareerPreference | None = None
    limit: Annotated[int, Field(ge=1, le=30)] | None = None

    @field_validator('regions','roles','owned_skills','required_skills','preferred_skills',mode='before')
    @classmethod
    def terms(cls,value):
        return SearchPlan.bounded_terms(value)

    @model_validator(mode='after')
    def supplied_values(self):
        if not self.model_fields_set or any(getattr(self,k) is None for k in self.model_fields_set):
            raise ValueError('A patch requires explicit non-null fields')
        return self

class IntentDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    target: Literal['jobs','training','selected','general','unspecified']
    action: Literal['chat','search','refine_search','next_results','consult','assessment_control','clarify','confirm_search','summary']
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    plan: SearchPlan | None = None
    changes: SearchChanges | None = None
    topics: Annotated[tuple[Annotated[str, Field(min_length=1, max_length=60)], ...], Field(max_length=8)] | None = None
    delivery_mode: Literal['online','offline','any'] | None = None
    task: Literal['prepare','interview','learning_plan','explain_unknown','defer','general'] | None = None
    control: Literal['stop','resume','preferred'] | None = None
    question: Annotated[str, Field(min_length=1,max_length=500)] | None = None

    @field_validator('topics',mode='before')
    @classmethod
    def topic_terms(cls,value):
        terms=SearchPlan.bounded_terms(value)
        if len(terms)>8 or any(len(t)>60 for t in terms):raise ValueError('Invalid training topic budget')
        return terms

    @model_validator(mode='after')
    def action_contract(self):
        fields=self.model_fields_set-{'target','action','reason'}
        allowed=set()
        if self.action in {'search','refine_search'}:
            if self.target=='jobs':
                key='plan' if self.action=='search' else 'changes'
                allowed={key}
                if getattr(self,key) is None:raise ValueError('Missing job search contract')
                if self.plan is not None and self.plan.schema_version!=2:raise ValueError('Version 2 required')
            elif self.target=='training':allowed={'topics','delivery_mode'}
            else:raise ValueError('Invalid search target')
        elif self.action=='next_results':
            if self.target not in {'jobs','training'}:raise ValueError('Invalid list target')
        elif self.action=='consult':
            allowed={'task'}
            if self.target!='selected' or self.task is None:raise ValueError('Selected counseling task required')
        elif self.action=='assessment_control':
            allowed={'control'}
            if self.target!='selected' or self.control is None:raise ValueError('Assessment control required')
        elif self.action in {'confirm_search'}:
            if self.target!='jobs':raise ValueError('Only job review can be confirmed')
        elif self.action=='summary':
            if self.target!='selected':raise ValueError('Selected summary required')
        elif self.action=='clarify':
            allowed={'question'}
            if self.question is None:raise ValueError('Clarification question required')
        elif self.action=='chat':
            if self.target=='unspecified':raise ValueError('Chat target required')
        if fields-allowed:raise ValueError('Fields do not match action')
        return self

    def to_dict(self):return self.model_dump(mode='json',exclude_unset=True)


def merge_search(plan, changes):
    previous=SearchPlan.parse(plan)
    if previous.schema_version!=2:raise ValueError('Legacy search needs a new plan')
    values=previous.to_dict()
    patch=changes.model_dump(mode='json',exclude_unset=True)
    if 'career' in patch:patch['career']={**values.get('career',{}),**patch['career']}
    values.update(patch)
    return SearchPlan.parse(values)
