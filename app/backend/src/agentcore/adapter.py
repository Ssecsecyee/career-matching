"""Bounded Harness inline loop; tools execute only against authenticated server state."""
import hashlib,json,time
from uuid import uuid4
from src.agentcore.contracts import SYSTEM,VERSION,tools
from src.services.dialogue import FlowError
from src.services.intent_context import assessment_facts
from src.services.memory import record,public_memory
from src.schemas.search import SearchPlan
from src.schemas.intent import IntentDecision
from src.services.context_router import ContextRouter

class HarnessFailure(RuntimeError):
    def __init__(self,code,usage):
        super().__init__(code);self.usage=usage

class HarnessAdapter:
    def __init__(self,client,arn,flow,session_id,owner,model_id,region,reserve):
        self.client,self.arn,self.flow=client,arn,flow
        self.session_id,self.actor=session_id,hashlib.sha256(owner.encode()).hexdigest()
        self.model_id,self.region,self.reserve=model_id,region,reserve

    def dispatch(self,name,args,state,payload):
        if not isinstance(args,dict):raise ValueError('Tool arguments must be an object')
        if name=='next_results':
            if set(args)!={'target'} or args['target'] not in {'jobs','training'}:raise ValueError('Invalid navigation target')
            decision=IntentDecision(target=args['target'],action='next_results',reason='Harness explicit result navigation')
            _,result,_=ContextRouter(self.flow).execute(state,payload,decision,None)
            return result,result
        if name=='get_saved_answers':
            if args:raise ValueError('No identity arguments allowed')
            selected=state.get('selected') or {}
            return {'selected_job':{k:selected.get(k) for k in ('title','company_name','source_id','source_version')},'assessment_facts':assessment_facts(state),'answer_details':[{'condition_id':c.get('condition_id'),'assessment':c.get('assessment'),'detail':str(c.get('detail',''))[:300]} for c in state.get('checks',[])[:12]]},None
        if name=='search_jobs':
            plan=SearchPlan.parse(args)
            if any(term.casefold() not in payload['message'].casefold() for term in plan.required_skills):raise ValueError('Required skills need explicit current user evidence')
            _,result,_=self.flow.execute_search(state,plan,plan.to_dict(),payload,require_review=True)
            return result,result
        if name=='search_training':
            if set(args)-{'topics','topic_operator','delivery_mode'}:raise ValueError('Unsupported training fields')
            decision=IntentDecision(target='training',action='search',reason='Harness tool',**args)
            _,result,_=ContextRouter(self.flow).preview_training(state,decision)
            return result,result
        raise ValueError('Tool is not allowed')

    def run(self,message,state,payload):
        self.reserve()
        state.setdefault('stage','conversation')
        runtime=state.setdefault('agentcore_runtime_session',str(uuid4()))
        # Fresh DB facts are authoritative even when remote memory is stale.
        snapshot={'selected_job':{k:(state.get('selected') or {}).get(k) for k in ('title','source_id','source_version')},'stage':state.get('stage'),'navigation_available':{'jobs':bool(state.get('search_navigation')),'training':bool(state.get('training_navigation'))},'conversation_target':state.get('conversation_target'),'search_plan':(state.get('search_navigation') or {}).get('plan'),'training_topics':(state.get('learning_context') or {}).get('topics',[])}
        messages=[{'role':'user','content':[{'text':json.dumps({'message':message[:4000],'server_context':snapshot},ensure_ascii=False)}]}]
        usage={'model_id':self.model_id,'region':self.region,'prompt_version':VERSION,'input_tokens':0,'output_tokens':0,'cache_read_input_tokens':0,'cache_write_input_tokens':0}
        start=time.monotonic();last_result=None;seen=set();trace=[]
        try:
            for round_no in range(3):
                blocks={};parts=[];stop=None
                response=self.client.invoke_harness(harnessArn=self.arn,runtimeSessionId=runtime,actorId=self.actor,
                    tools=tools(),allowedTools=['@*/'+t['name'] for t in tools()],systemPrompt=[{'text':SYSTEM}],
                    maxIterations=3,maxTokens=900,timeoutSeconds=45,messages=messages)
                stream=response['stream']
                try:
                    for event in stream:
                        if any(k in event for k in ('validationException','internalServerException','runtimeClientError')):raise RuntimeError('AgentCore stream failure')
                        if 'contentBlockStart' in event:
                            value=event['contentBlockStart'];tool=value.get('start',{}).get('toolUse')
                            if tool:blocks[value['contentBlockIndex']]={'name':tool['name'],'id':tool['toolUseId'],'input':''}
                        if 'contentBlockDelta' in event:
                            value=event['contentBlockDelta'];delta=value.get('delta',{})
                            if 'text' in delta:parts.append(delta['text'])
                            if 'toolUse' in delta:
                                if value['contentBlockIndex'] not in blocks:raise RuntimeError('Invalid tool stream')
                                blocks[value['contentBlockIndex']]['input']+=delta['toolUse'].get('input','')
                            if sum(len(x) for x in parts)>12000 or any(len(b['input'])>10000 for b in blocks.values()):raise RuntimeError('AgentCore output too large')
                        if 'messageStop' in event:stop=event['messageStop'].get('stopReason')
                        if 'metadata' in event:
                            u=event['metadata'].get('usage',{})
                            for local,key in [('input_tokens','inputTokens'),('output_tokens','outputTokens'),('cache_read_input_tokens','cacheReadInputTokens'),('cache_write_input_tokens','cacheWriteInputTokens')]:usage[local]+=u.get(key,0) or 0
                finally:
                    if hasattr(stream,'close'):stream.close()
                if stop=='end_turn':
                    reply=''.join(parts).strip()
                    if not reply:raise RuntimeError('Empty AgentCore reply')
                    record(state,message,'statement');record(state,reply,'assistant')
                    state['agentcore_tool_trace']=(state.get('agentcore_tool_trace',[])+trace)[-20:]
                    result=dict(last_result or {'stage':'conversation'},message=reply,memory=public_memory(state),engine='agentcore')
                    usage['latency_ms']=round((time.monotonic()-start)*1000)
                    return result,usage
                if stop!='tool_use' or not blocks or round_no==2:raise RuntimeError('AgentCore execution limit')
                results=[]
                for block in blocks.values():
                    if block['id'] in seen or len(seen)>=3:raise RuntimeError('Repeated or excessive tool call')
                    seen.add(block['id']);args=json.loads(block['input'] or '{}')
                    try:
                        output,result=self.dispatch(block['name'],args,state,payload)
                        if result is not None:last_result=result
                        status='success';trace.append({'tool':block['name'],'tool_use_id':block['id'],'status':status,'search_id':output.get('search_id')})
                    except (ValueError,FlowError):
                        output={'error':'Tool parameters were rejected. Ask the user to clarify; do not invent results.'};status='error';trace.append({'tool':block['name'],'tool_use_id':block['id'],'status':status})
                    text=json.dumps(output,ensure_ascii=False,default=str)
                    if len(text)>18000:raise RuntimeError('Tool result too large')
                    results.append({'toolResult':{'toolUseId':block['id'],'content':[{'text':text}],'status':status}})
                messages=[{'role':'user','content':results}]
            raise RuntimeError('AgentCore execution limit')
        except Exception as exc:
            usage['latency_ms']=round((time.monotonic()-start)*1000)
            raise HarnessFailure(type(exc).__name__,usage) from None
