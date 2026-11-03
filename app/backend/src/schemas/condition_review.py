"""Bounded model proposal; source evidence is validated separately."""
from typing import Annotated,Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

POLICY_VERSION='condition-review-v2'
class Logic(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,json_schema_extra={
        'allOf':[
            {'if':{'properties':{'operator':{'const':'unresolved'}}},'then':{'properties':{'children':{'maxItems':0},'term':{'type':'null'},'evidence':{'type':'null'}}}},
            {'if':{'properties':{'operator':{'const':'atom'}}},'then':{'required':['term','evidence'],'properties':{'children':{'maxItems':0},'term':{'type':'string','minLength':1},'evidence':{'type':'string','minLength':1}}}},
            {'if':{'properties':{'operator':{'enum':['all','any']}}},'then':{'required':['children'],'properties':{'children':{'minItems':2},'term':{'type':'null'},'evidence':{'type':'null'}}}}
        ]})
    operator:Literal['atom','all','any','unresolved']
    term:Annotated[str,Field(min_length=1,max_length=120)]|None=None
    evidence:Annotated[str,Field(min_length=1,max_length=2000)]|None=None
    children:list['Logic']=Field(default_factory=list,max_length=8)
    @model_validator(mode='after')
    def shape(self):
        if self.operator=='atom':
            if not self.term or not self.evidence or not self.term.strip() or not self.evidence.strip() or self.children:raise ValueError('Invalid atom')
        elif self.term is not None or self.evidence is not None:raise ValueError('Only atoms have terms')
        elif self.operator=='unresolved' and self.children:raise ValueError('Unresolved has no children')
        elif self.operator in {'all','any'} and len(self.children)<2:raise ValueError('Two children required')
        return self

class ExtractedPart(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    part_id:Annotated[str,Field(min_length=16,max_length=16)]
    terms:list[Annotated[str,Field(min_length=1,max_length=120)]]=Field(max_length=40)

class ConditionDecision(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    condition_id:Annotated[str,Field(min_length=64,max_length=64)]
    treatment:Literal['ask','reference','review']
    category:Literal['skill','experience','education','certificate','attitude','other']
    reason_code:Literal['verifiable_requirement','no_restriction','subjective_trait','not_eligibility','ambiguous']
    reason:Annotated[str,Field(min_length=1,max_length=400)]
    logic:Logic
    parts:list[ExtractedPart]=Field(min_length=1,max_length=128)
    @model_validator(mode='after')
    def reason_contract(self):
        if not self.reason.strip():raise ValueError('Empty reason')
        allowed={'ask':{'verifiable_requirement'},'reference':{'no_restriction','subjective_trait','not_eligibility'},'review':{'ambiguous'}}
        if self.reason_code not in allowed[self.treatment]:raise ValueError('Reason does not match treatment')
        if self.reason_code=='subjective_trait' and self.category!='attitude':raise ValueError('Subjective traits require attitude category')
        return self

class ConditionReview(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    conditions:list[ConditionDecision]=Field(max_length=80)
