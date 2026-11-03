"""Resolve only the selected job. Structural validation is not independent semantic approval."""
from src.bedrock.model_json import ModelOutputTruncatedError
from src.repositories.condition_question_cache import QuestionCacheSourceChanged
from src.services.condition_review import condition_hash,validated_envelope

class SelectedConditionReview:
    def __init__(self,jobs,cache,classifier,*,approved=None,max_calls=5):
        self.jobs,self.cache,self.classifier,self.approved=jobs,cache,classifier,approved
        self.max_calls=max_calls
    def current(self,job):
        row=self.jobs.get(str(job['source_id']))
        from src.services.dialogue import ensure_selectable
        ensure_selectable(row,True)
        if row['job_id']!=job['job_id'] or condition_hash(row)!=condition_hash(job):raise QuestionCacheSourceChanged('Selected conditions changed')
        return row
    def resolve(self,job,invoke):
        try:
            self.current(job)
            if self.approved is not None:
                known=self.approved.get(job)
                if known is not None:return {'review':validated_envelope(job,known),'source':'approved_review','validation_level':'approved_source_review'}
            known=self.cache.get(job)
            if known is not None:return {'review':known,'source':'question_cache','validation_level':'source_contract_only'}
            if invoke is None:return {'review':None,'status':'model_not_requested'}
            with self.cache.claim(job) as acquired:
                if not acquired:return {'review':None,'status':'review_in_progress_all_questions'}
                known=self.cache.get(job)
                if known is not None:return {'review':known,'source':'question_cache','validation_level':'source_contract_only'}
                self.current(job)
                try:review,usage=self.classifier.classify(job,mode='adaptive',invoke=invoke,max_calls=self.max_calls,max_seconds=30)
                except ModelOutputTruncatedError as exc:
                    # Only split a truncated whole-job call when it is genuinely a smaller plan.
                    bounded=self.classifier.plan(job,'bounded');adaptive=self.classifier.plan(job,'adaptive')
                    spent=getattr(exc,'usage',{});used=spent.get('calls',1)
                    if len(adaptive)!=1 or len(bounded)<=1 or used+len(bounded)>self.max_calls:raise
                    review,usage=self.classifier.classify(job,mode='bounded',invoke=invoke,max_calls=self.max_calls-used,max_seconds=max(0,30-spent.get('latency_ms',0)/1000))
                    usage=dict(usage,initial_truncated_attempt=spent)
                    for key in ('input_tokens','output_tokens','cache_read_input_tokens','cache_write_input_tokens'):
                        usage[key]=None if usage.get(key) is None or spent.get(key) is None else usage[key]+spent[key]
                    usage['calls']=usage.get('calls',0)+used
                self.current(job)
                checked=validated_envelope(job,review)
                saved=self.cache.save(job,checked,usage)
                return {'review':saved,'source':'generated_question_cache','validation_level':'source_contract_only'}
        except QuestionCacheSourceChanged:raise
        except Exception as exc:
            # Do not apply an uncached/failed result or convert failure into user eligibility.
            return {'review':None,'status':'fallback_all_questions','error_type':type(exc).__name__}
