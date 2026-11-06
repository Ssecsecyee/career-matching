"""Versioned, strictly validated search intent; v1 remains an explicit compatibility path."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

Term = Annotated[StrictStr, Field(min_length=1, max_length=80)]
Terms = Annotated[tuple[Term, ...], Field(max_length=10)]


class CareerPreference(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    levels: tuple[Literal['entry', 'junior', 'experienced'], ...] = ()
    max_years: Annotated[int, Field(ge=0, le=60)] | None = None

    @field_validator('levels', mode='before')
    @classmethod
    def levels_list(cls, value):
        if not isinstance(value, (list, tuple)) or len(value) > 3:
            raise ValueError('Invalid career levels')
        if any(not isinstance(v, str) for v in value):
            raise ValueError('Invalid career level')
        return tuple(dict.fromkeys(value))


class SearchPlan(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    # Deprecated fields retain the original literal/AND meaning for old clients.
    text_field: Literal['all','title','company_name','responsibilities','qualifications','preferred_requirements','tech_stacks'] = 'all'
    keyword: Annotated[str, Field(max_length=120)] = ''
    region: Annotated[str, Field(max_length=80)] = ''
    skills: Terms = ()
    limit: Annotated[int, Field(ge=1, le=30)] = 5
    schema_version: Literal[1, 2] = 1
    target: Literal['jobs'] = 'jobs'
    regions: Terms = ()
    roles: Terms = ()
    owned_skills: Terms = ()
    required_skills: Terms = ()
    preferred_skills: Terms = ()
    career: CareerPreference = Field(default_factory=CareerPreference)

    def __init__(self, *args, **data):
        # Older offline experiments construct the four-field dataclass positionally.
        if len(args) > 4:
            raise ValueError('Invalid positional search fields')
        for name, value in zip(('keyword', 'region', 'skills', 'limit'), args):
            if name in data:
                raise ValueError('Duplicate search field')
            data[name] = value
        if any(k in data for k in ('regions', 'roles', 'owned_skills', 'required_skills', 'preferred_skills', 'career', 'target')):
            data.setdefault('schema_version', 2)
        super().__init__(**data)

    @field_validator('skills', 'regions', 'roles', 'owned_skills', 'required_skills', 'preferred_skills', mode='before')
    @classmethod
    def bounded_terms(cls, value):
        if not isinstance(value, (list, tuple)) or len(value) > 10:
            raise ValueError('Expected at most ten search terms')
        if any(not isinstance(v, str) or not v.strip() or len(v) > 80 for v in value):
            raise ValueError('Invalid search term')
        result = []
        for item in value:
            item = item.strip()
            if item.casefold() not in {v.casefold() for v in result}:
                result.append(item)
        return tuple(result)

    @field_validator('schema_version', mode='before')
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError('Invalid search schema version')
        return value

    @field_validator('keyword', 'region')
    @classmethod
    def trim_text(cls, value):
        return value.strip()

    @model_validator(mode='after')
    def no_mixed_contract(self):
        if self.schema_version == 2 and (self.keyword or self.region or self.skills):
            raise ValueError('Do not mix legacy filters with structured intent')
        if self.schema_version == 1 and (self.regions or self.roles or self.owned_skills or
                self.required_skills or self.preferred_skills or self.career.levels or self.career.max_years is not None):
            raise ValueError('Structured intent requires version 2')
        return self

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):
            raise ValueError('Search plan must be an object')
        return cls(**value)

    def to_dict(self):
        if self.schema_version == 1:
            return {**{k: self.model_dump(mode='json')[k] for k in ('keyword', 'region', 'skills', 'limit')},**({'text_field':self.text_field} if self.text_field!='all' else {})}
        return self.model_dump(mode='json', exclude={'keyword', 'region', 'skills'})
