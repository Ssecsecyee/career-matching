"""Application-owned context routing contract. No executable DSL or arbitrary keys."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from src.schemas.search import SearchPlan, CareerPreference, Terms

INTENT_VERSION = 'context-intent-v4'

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

class IntentJobPlan(BaseModel):
    """Version-2-only model boundary; legacy fields never appear in the router schema."""
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_version: Literal[2] = 2
    target: Literal['jobs'] = 'jobs'
    regions: Terms = ()
    roles: Terms = ()
    owned_skills: Terms = ()
    required_skills: Terms = ()
    preferred_skills: Terms = ()
    career: CareerPreference = Field(default_factory=CareerPreference)
    limit: Annotated[int, Field(ge=1, le=30)] = 5

    @field_validator('regions','roles','owned_skills','required_skills','preferred_skills',mode='before')
    @classmethod
    def terms(cls,value):return SearchPlan.bounded_terms(value)

    @field_validator('schema_version',mode='before')
    @classmethod
    def version(cls,value):
        if type(value) is not int:raise ValueError('Invalid intent search version')
        return value

    def as_search_plan(self):return SearchPlan.parse(self.model_dump(mode='json'))


class RequiredSkillEvidence(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    skill: Annotated[str, Field(min_length=1, max_length=60)]
    quote: Annotated[str, Field(min_length=1, max_length=500)]


class IntentDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    target: Literal['jobs','training','selected','general','unspecified']
    action: Literal['chat','search','refine_search','next_results','consult','assessment_control','clarify','confirm_search','summary','remember']
    reason: Annotated[str, Field(min_length=1, max_length=500)]
    ask_assessment: bool | None = None
    search_basis: Literal['user_request','assessment'] = 'user_request'
    required_skill_evidence: Annotated[list[RequiredSkillEvidence], Field(max_length=20)] = Field(default_factory=list)
    plan: IntentJobPlan | None = None
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
        fields=self.model_fields_set-{'target','action','reason','ask_assessment'}
        if 'ask_assessment' in self.model_fields_set and self.ask_assessment is None:
            raise ValueError('Preference must be an explicit boolean')
        allowed=set()
        if self.action in {'search','refine_search'}:
            if self.target=='jobs':
                key='plan' if self.action=='search' else 'changes'
                allowed={key,'search_basis','required_skill_evidence'}
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
        elif self.action=='remember':
            if self.target!='selected':raise ValueError('Correction targets saved experience')
        elif self.action in {'confirm_search'}:
            if self.target!='jobs':raise ValueError('Only job review can be confirmed')
        elif self.action=='summary':
            if self.target!='selected':raise ValueError('Selected summary required')
        elif self.action=='clarify':
            allowed={'question'}
            if self.question is None:raise ValueError('Clarification question required')
        elif self.action=='chat':
            if self.target=='unspecified':raise ValueError('Chat target required')
        if self.action=='assessment_control' and self.ask_assessment is not None:
            if self.ask_assessment != (self.control!='stop'):raise ValueError('Conflicting assessment preference')
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
